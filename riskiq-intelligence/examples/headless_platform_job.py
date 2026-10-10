"""Run the same core in a Python job/notebook after authorised data preparation.
Not a certified native Databricks/Snowflake/Foundry deployment.
No extraction or external write is performed by this example itself.
"""
from pathlib import Path
import json
import pandas as pd
from riskiq.cli import analyse_frame
from riskiq.schemas import RunCreate

def run_prepared_dataframe(frame: pd.DataFrame, output_directory: str) -> None:
    if len(frame)>100_000:
        raise ValueError("Bounded reference core: prepare a smaller approved cohort")
    spec=RunCreate(dataset_id="platform-prepared-data").model_dump()
    bundle,evidence=analyse_frame(frame,spec)
    path=Path(output_directory);path.mkdir(parents=True,exist_ok=True)
    (path/"candidate-tariff.json").write_text(json.dumps(bundle,indent=2),encoding="utf-8")
    (path/"evidence.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")

# In an authorised notebook, after constructing a bounded Pandas DataFrame:
# run_prepared_dataframe(prepared_frame, "./local-output")
# Publish only through the client's approved governance process.
