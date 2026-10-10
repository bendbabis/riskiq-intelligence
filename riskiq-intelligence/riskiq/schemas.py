"""Versioned public contracts; no untyped code, filters or client system messages."""
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Feature(Strict):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["numeric", "categorical"]
    nonlinear: bool = False

class Mapping(Strict):
    policy_id: str = "policy_id"
    exposure: str = "exposure"
    claim_count: str = "claim_count"
    claim_amount: str = "claim_amount"
    premium: str = "premium_ht"
    period: str | None = "period"
    coverage: str | None = "coverage"
    coverage_value: str | None = "RC"
    features: list[Feature] = Field(default_factory=lambda: [
        Feature(name="driver_age",kind="numeric",nonlinear=True),
        Feature(name="vehicle_power",kind="numeric"),
        Feature(name="region",kind="categorical"),
        Feature(name="usage",kind="categorical")], min_length=1, max_length=20)
    max_exposure: float | None = Field(default=1.0, gt=0)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    @model_validator(mode="after")
    def feature_roles(self):
        names = [f.name for f in self.features]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate features")
        protected = {self.policy_id, self.exposure, self.claim_count, self.claim_amount,
                     self.premium, self.period, self.coverage}
        if set(names) & protected:
            raise ValueError("Identifiers, dates, exposure and outcomes cannot be predictors")
        if (self.coverage is None) != (self.coverage_value is None):
            raise ValueError("coverage and coverage_value must both be set, or both be null")
        return self

class PricingPolicy(Strict):
    expense_ratio: float = Field(default=.30, ge=0, lt=.8)
    tax_rate: float = Field(default=0, ge=0, le=1)
    base_retention: float = Field(default=.90, gt=0, le=1)
    elasticity: float = Field(default=1.2, ge=0, le=10)
    min_retention: float = Field(default=.86, gt=0, le=1)
    max_increase: float = Field(default=.15, ge=0, le=1)
    max_decrease: float = Field(default=.10, ge=0, le=.8)
    max_average_increase: float = Field(default=.08, ge=0, le=1)
    segment: str = "usage"
    @model_validator(mode="after")
    def coherent(self):
        if self.min_retention > self.base_retention:
            raise ValueError("min_retention cannot exceed the baseline in this release")
        return self

class RunCreate(Strict):
    dataset_id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="Pricing intelligence review", min_length=1, max_length=120)
    mapping: Mapping = Field(default_factory=Mapping)
    policy: PricingPolicy = Field(default_factory=PricingPolicy)
    alpha: float = Field(default=.01, ge=0, le=10)
    trigger: Literal["manual", "monitoring"] = "manual"
    parent_run_id: str | None = None
    @model_validator(mode="after")
    def segment_exists(self):
        if self.policy.segment not in [f.name for f in self.mapping.features if f.kind == "categorical"]:
            raise ValueError("The optimisation segment must be a declared categorical feature")
        return self

class Login(Strict):
    email: str = Field(min_length=3,max_length=200)
    password: str = Field(min_length=1,max_length=256)
    tenant: str = Field(default="demo",pattern=r"^[a-z0-9_-]{1,40}$")

class UserCreate(Strict):
    email: str = Field(min_length=3,max_length=200)
    password: str = Field(min_length=12,max_length=256)
    role: Literal["admin","analyst","approver","viewer"]

class Approval(Strict):
    decision: Literal["approve","reject"]
    comment: str = Field(min_length=10, max_length=2000)
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

class Note(Strict):
    comment: str = Field(min_length=10,max_length=2000)

class MonitorRequest(Strict):
    dataset_id: str
    maturity_confirmed: bool = False
    min_exposure: float = Field(default=100,ge=10)

class CopilotRequest(Strict):
    message: str = Field(min_length=1,max_length=3000)
    run_id: str | None = None
    use_llm: bool = False

class DemoCreate(Strict):
    n: int = Field(default=5000,ge=1000,le=50000)
    seed: int = Field(default=42,ge=0,le=2147483647)
    shock: float = Field(default=1.0,gt=0,le=3)
    period_shift: int = Field(default=0,ge=0,le=12)

class ImportRemote(Strict):
    source: str = Field(pattern=r"^[a-z0-9_-]{1,60}$")
    table: str = Field(min_length=1,max_length=250)
    name: str = Field(default="Connected dataset",min_length=1,max_length=120)

class FilterTerm(Strict):
    column: str
    operator: Literal["eq","ne","gt","ge","lt","le","in"]
    value: str | float | int | list[str | float | int]

class Transform(Strict):
    name: str = Field(min_length=1,max_length=120)
    filters: list[FilterTerm] = Field(default_factory=list,max_length=20)
    rename: dict[str,str] = Field(default_factory=dict,max_length=40)

class QuoteRequest(Strict):
    risk: dict[str, str | float | int | None] = Field(min_length=1, max_length=40)
    previous_premium: float = Field(gt=0, le=1e9)
