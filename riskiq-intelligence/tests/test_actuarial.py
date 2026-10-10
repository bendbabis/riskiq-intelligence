import copy,json
import numpy as np
import pandas as pd
import pytest
from riskiq.schemas import RunCreate,Mapping,PricingPolicy
from riskiq.core.data import synthetic,quality,read_csv_bytes,select_coverage,transform
from riskiq.core.modeling import train_candidates,fit_component,design_fit,matrix,weighted_gini,reference_distributions,psi,split
from riskiq.core.scoring import score_one,score_records,quote
from riskiq.core.pricing import simulate,optimise

@pytest.fixture(scope='module')
def fitted():
    df=synthetic(5000); s=RunCreate(dataset_id='test').model_dump()
    r=train_candidates(df,s['mapping'],s['alpha'])
    return df,s,r

def test_synthetic_reproducible():
    pd.testing.assert_frame_equal(synthetic(1000),synthetic(1000))

def test_french_csv_decimal_encoding():
    raw='nom;exposition;prime\nÎle-de-France;0,50;123,45\n'.encode('cp1252')
    df=read_csv_bytes(raw,decimal=',',encoding='cp1252')
    assert df['prime'].iloc[0]==123.45 and df['exposition'].iloc[0]==.5

@pytest.mark.parametrize('raw',[b'',b'a,a\n1,2\n',b'a,b\n1,\x00\n'])
def test_bad_csv_rejected(raw):
    with pytest.raises(ValueError): read_csv_bytes(raw,separator=',')

def test_quality_detects_actuarial_defects():
    df=synthetic(1000); df.loc[0,'exposure']=-.3;df.loc[1,'claim_count']=-1;df.loc[2,'claim_amount']=-500;df.loc[3,'period']='2023-13-45'
    q=quality(df,Mapping().model_dump());assert not q['passed']
    failed={x['code'] for x in q['checks'] if not x['passed']}
    assert {'positive_exposure','nonnegative_integer_count','nonnegative_loss','valid_dates'}<=failed

def test_exposure_basis_can_be_configured():
    df=synthetic(1000);df['exposure']*=3;m=Mapping(max_exposure=None).model_dump()
    assert quality(df,m)['passed']

def test_real_filters_and_rename():
    df=synthetic(1000);out=transform(df,{'filters':[{'column':'driver_age','operator':'ge','value':60}],'rename':{'driver_age':'age'},'name':'prepared'})
    assert len(out)<len(df) and out.age.min()>=60 and 'driver_age' in df

def test_no_expression_execution():
    with pytest.raises(ValueError): transform(synthetic(1000),{'filters':[{'column':'driver_age','operator':'eval','value':'danger'}],'rename':{}})

def test_split_final_test_separate(fitted):
    df,s,r=fitted;folds,info=split(df,s['mapping'])
    assert not info['final_test_used_for_selection'] and not info['group_overlap']
    assert max(df.iloc[folds[0]].period)<min(df.iloc[folds[1]].period)
    assert max(df.iloc[folds[1]].period)<min(df.iloc[folds[2]].period)

def test_repeated_policy_time_leakage_blocked():
    df=synthetic(5000);df.loc[0,'policy_id']='shared';df.loc[0,'period']='2022-01-01';df.loc[1,'policy_id']='shared';df.loc[1,'period']='2024-01-01'
    with pytest.raises(ValueError,match='cross time'):split(df,Mapping().model_dump())

def test_gamma_count_weighted_target():
    n=np.tile([1,2,4,8],100);df=pd.DataFrame({'x':np.arange(400)%7,'exposure':.4,'claim_count':n,'claim_amount':n*1000.})
    m=Mapping(features=[{'name':'x','kind':'numeric'}]).model_dump()
    b=fit_component(df,m,'severity',0)
    assert np.allclose(score_records(b,df.to_dict('records')),1000,rtol=1e-6)
    assert b['exposure_handling']=='loss/count target; claim-count weights'

def test_frequency_rate_unit():
    n=np.tile([1,2,4,8],100);df=pd.DataFrame({'x':np.arange(400)%7,'exposure':n*10.,'claim_count':n,'claim_amount':n*1000.})
    m=Mapping(features=[{'name':'x','kind':'numeric'}]).model_dump();b=fit_component(df,m,'frequency',0)
    assert np.allclose(score_records(b,df.to_dict('records')),.1,rtol=1e-6)

def test_json_export_singleton_batch_parity(fitted):
    df,s,r=fitted;b=json.loads(json.dumps(r['model']));records=df.head(30).to_dict('records');batch=score_records(b,records)
    assert np.allclose(batch,[score_one(b,x) for x in records],rtol=0,atol=0)
    assert np.allclose(batch,score_records(r['model'],records),rtol=0,atol=0)

def test_numeric_integer_and_underscore_types_preserved(fitted):
    df,s,r=fitted;b=r['candidates'][1]['bundle'];f=[x for x in b['design']['features'] if x['name']=='vehicle_power'][0]
    assert f['kind']=='numeric'
    row=df.iloc[0].to_dict();row['vehicle_power']=4;p1=score_one(b,row);row['vehicle_power']=15;p2=score_one(b,row)
    assert not np.isclose(p1,p2)

def test_train_imputation_frozen(fitted):
    df,s,r=fitted;b=r['candidates'][1]['bundle'];f=b['design']['features'][0];row=df.iloc[0].to_dict();row[f['name']]=None;p1=score_one(b,row);row[f['name']]=f['median'];assert p1==score_one(b,row)

@pytest.mark.parametrize('risk',[{}, {'driver_age':35,'vehicle_power':8,'usage':'Unknown','region':'North'}])
def test_bad_risks_refer_not_price(fitted,risk):
    with pytest.raises(ValueError):score_one(fitted[2]['model'],risk)

def test_category_case_normalisation(fitted):
    row=fitted[0].iloc[0].to_dict();b=fitted[2]['model'];p=score_one(b,row);row['usage']=row['usage'].lower();assert p==score_one(b,row)

def test_gini_direction_and_ties():
    e=np.ones(4);y=np.array([0,0,0,4.]);assert weighted_gini(y,[1,2,3,4],e)>0;assert weighted_gini(y,[4,3,2,1],e)<0;assert weighted_gini(y,[1,1,1,1],e)==0

def test_unchanged_scenario_is_neutral():
    p=np.array([100,150.,200]);s=simulate(p,p,p*.7,np.ones(3),PricingPolicy().model_dump())
    assert s['delta_margin']==0 and s['delta_earned_premium']==0 and s['average_price_change']==0

def test_scaled_optimisation_same_decision(fitted):
    df,s,r=fitted;policy=s['policy'];a=optimise(df,s['mapping'],r['model'],policy)
    scaled=df.copy();scaled['premium_ht']*=1000;scaled['claim_amount']*=1000;model=copy.deepcopy(r['model'])
    if model['kind']=='frequency_severity':model['severity']['intercept']+=np.log(1000)
    else:model['intercept']+=np.log(1000)
    b=optimise(scaled,s['mapping'],model,policy)
    assert a['feasible'] and b['feasible']
    assert np.allclose(list(a['factors'].values()),list(b['factors'].values()),rtol=2e-5,atol=2e-5)

def test_optimisation_constraints_and_quote_reconcile(fitted):
    df,s,r=fitted;o=optimise(df,s['mapping'],r['model'],s['policy']);sim=o['simulation'];assert sim['after']['retention']>=s['policy']['min_retention']-1e-7
    assert sim['average_price_change']<=s['policy']['max_average_increase']+1e-7
    plan={'schema':'riskiq.tariff/1','model':r['model'],'policy':{**s['policy'],'tax_rate':.18},'factors':o['factors'],'coverage':'RC','currency':'EUR'}
    q=quote(plan,df.iloc[0].to_dict(),float(df.iloc[0].premium_ht))
    from decimal import Decimal
    assert Decimal(q['premium_ht'])+Decimal(q['tax'])==Decimal(q['premium_ttc'])

def test_shift_outside_training_detected():
    df=synthetic(2000);m=Mapping().model_dump();ref=reference_distributions(df,m);shift=df.copy();shift['driver_age']+=1000
    rows=psi(ref,shift);assert next(x for x in rows if x['feature']=='driver_age')['psi']>.25

def test_l1_not_silently_accepted():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):RunCreate(dataset_id='x',l1_ratio=.5)

@pytest.mark.parametrize('field',['claim_count','claim_amount','exposure','premium_ht','policy_id'])
def test_outcome_predictor_blocked(field):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):Mapping(features=[{'name':field,'kind':'numeric'}])
