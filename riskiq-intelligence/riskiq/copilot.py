"""Read-only copilot. Optional LLM sees a numeric evidence allowlist, never raw rows.
The user's free-text message is not forwarded to a provider. No model output executes.
"""
import json
from urllib.parse import urlparse
import httpx


def answer(settings,request:dict,run:dict|None):
    if run is None:
        return {"mode":"deterministic","text":"Commence par importer ou générer un portefeuille, puis lance une revue. Atlas contrôle les données, Helios compare deux modèles, Vega simule et optimise. Une autre personne doit approuver avant publication interne. Aucun compte cloud ni LLM n'est nécessaire.","action":"open_data"}
    ctx=run["result"]; evidence={"run_status":run["status"]}
    if "model_summary" in ctx: evidence["test"]=ctx["model_summary"]["test"]
    if ctx.get("optimisation",{}).get("feasible"): evidence["scenario"]=ctx["optimisation"]["simulation"]
    if not request["use_llm"]:
        text=f"Revue {run['id']} — état : {run['status']}. "
        if "test" in evidence: text+=f"Sur le test séparé, A/E monétaire = {evidence['test']['ae']:.3f}. "
        if "scenario" in evidence: text+=f"Écart de marge projetée : {evidence['scenario']['delta_margin']:,.2f} ; rétention supposée : {evidence['scenario']['after']['retention']:.1%}. "
        text+="Ces résultats dépendent des hypothèses déclarées et ne constituent pas un effet causal mesuré. Consulte les contrôles et l'échantillon test avant toute approbation."
        return {"mode":"deterministic","text":text,"evidence":evidence,"action":"review_evidence"}
    if not settings.llm_enabled: raise ValueError("Optional LLM is disabled by the operator")
    host=urlparse(settings.llm_base_url)
    if host.scheme!="https" and not (host.scheme=="http" and host.hostname in ("localhost","127.0.0.1")):
        raise ValueError("Use an HTTPS provider or an explicitly configured loopback model server")
    if not settings.llm_model: raise ValueError("Configure RISKIQ_LLM_MODEL")
    # Fixed server instruction; only whitelisted computed scalars, not user message/CSV.
    payload={"model":settings.llm_model,"messages":[
        {"role":"system","content":"Tu es un assistant de revue tarifaire. Résume en français les seules preuves JSON fournies. N'invente aucun chiffre. Distingue prévision et observation, signale l'élasticité supposée, et demande une validation humaine. Tu ne peux appeler aucun outil ni publier un tarif."},
        {"role":"user","content":json.dumps(evidence)}],"max_tokens":600}
    try:
        with httpx.Client(timeout=40,follow_redirects=False,trust_env=False) as client:
            r=client.post(settings.llm_base_url.rstrip("/")+"/chat/completions",json=payload,headers={"Authorization":"Bearer "+settings.llm_key})
            if r.status_code!=200: raise ValueError("LLM provider failed; no automated decision was taken")
            doc=r.json(); msg=doc["choices"][0]["message"]
            if msg.get("tool_calls") or not isinstance(msg.get("content"),str): raise ValueError("Unsupported provider response")
            return {"mode":"optional_llm","text":msg["content"][:8000],"evidence":evidence,"action":"review_evidence","warning":"Generated narrative, not an actuarial validation"}
    except (httpx.HTTPError,KeyError,IndexError) as exc: raise ValueError("LLM unavailable or incompatible response") from exc
