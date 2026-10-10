"""Generate LOCAL secrets; never overwrite an existing installation."""
import secrets
from pathlib import Path
root=Path(__file__).resolve().parents[1]
env=root/".env"
if env.exists():
    raise SystemExit(".env already exists; left unchanged. Read your .local-credentials.txt or use your existing accounts.")
a=secrets.token_urlsafe(24); b=secrets.token_urlsafe(24); key=secrets.token_hex(32)
content=f'''RISKIQ_MODE=local
RISKIQ_PUBLIC_URL=http://127.0.0.1:8080
RISKIQ_DATABASE_URL=sqlite:///./var/riskiq.db
RISKIQ_COOKIE_SECURE=false
RISKIQ_AUDIT_KEY={key}
RISKIQ_EMBEDDED_WORKER=true
RISKIQ_BOOTSTRAP_TENANT=demo
RISKIQ_BOOTSTRAP_ADMIN_EMAIL=admin@riskiq.local
RISKIQ_BOOTSTRAP_ADMIN_PASSWORD={a}
RISKIQ_BOOTSTRAP_APPROVER_EMAIL=approver@riskiq.local
RISKIQ_BOOTSTRAP_APPROVER_PASSWORD={b}
RISKIQ_LLM_ENABLED=false
'''
env.write_text(content,encoding="utf-8"); env.chmod(0o600)
creds=root/".local-credentials.txt"
creds.write_text(f"LOCAL SECRETS — DO NOT COMMIT OR SEND\nTenant: demo\nAdmin: admin@riskiq.local\nPassword: {a}\nReviewer: approver@riskiq.local\nPassword: {b}\n",encoding="utf-8"); creds.chmod(0o600)
print("Created .env and .local-credentials.txt. Keep both private. Start the app, then open http://127.0.0.1:8080.")
