"""Server-side configuration. No cloud account or LLM is required."""
from dataclasses import dataclass
import os
from pathlib import Path

@dataclass
class Settings:
    database_url: str = "sqlite:///./var/riskiq.db"
    audit_key: str = ""
    cookie_secure: bool = False
    public_url: str = "http://127.0.0.1:8080"
    embedded_worker: bool = True
    sources_file: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_key: str = ""
    llm_enabled: bool = False
    mode: str = "local"

    @classmethod
    def load(cls):
        envfile=Path(".env")
        if envfile.exists():
            for line in envfile.read_text(encoding="utf-8-sig").splitlines():
                if not line.strip() or line.lstrip().startswith("#") or "=" not in line: continue
                key,value=line.split("=",1)
                if key.strip().startswith("RISKIQ_"): os.environ.setdefault(key.strip(),value.strip())
        Path("var").mkdir(exist_ok=True)
        key=os.getenv("RISKIQ_AUDIT_KEY","")
        keyfile=Path("var/audit.key")
        if not key:
            if not keyfile.exists():
                import secrets
                keyfile.write_text(secrets.token_hex(32)); keyfile.chmod(0o600)
            key=keyfile.read_text().strip()
        obj=cls(database_url=os.getenv("RISKIQ_DATABASE_URL",cls.database_url),audit_key=key,
                cookie_secure=os.getenv("RISKIQ_COOKIE_SECURE","false").lower()=="true",
                public_url=os.getenv("RISKIQ_PUBLIC_URL",cls.public_url).rstrip("/"),
                embedded_worker=os.getenv("RISKIQ_EMBEDDED_WORKER","true").lower()=="true",
                sources_file=os.getenv("RISKIQ_SOURCES_FILE",""),
                llm_base_url=os.getenv("RISKIQ_LLM_BASE_URL",""),llm_model=os.getenv("RISKIQ_LLM_MODEL",""),
                llm_key=os.getenv("RISKIQ_LLM_KEY",""),llm_enabled=os.getenv("RISKIQ_LLM_ENABLED","false").lower()=="true",
                mode=os.getenv("RISKIQ_MODE","local"))
        if obj.mode=="server" and (not obj.cookie_secure or not obj.public_url.startswith("https://") or not os.getenv("RISKIQ_AUDIT_KEY")):
            raise ValueError("Server mode requires HTTPS, secure cookies and a persistent RISKIQ_AUDIT_KEY")
        return obj
