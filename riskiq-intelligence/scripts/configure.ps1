$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (Test-Path "$root/.env") { throw ".env exists and has been left unchanged." }
function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes); $rng.Dispose()
    return [Convert]::ToBase64String($bytes).Replace('+','-').Replace('/','_').TrimEnd('=')
}
$a = New-Secret; $b = New-Secret; $key = New-Secret
@"
RISKIQ_MODE=local
RISKIQ_PUBLIC_URL=http://127.0.0.1:8080
RISKIQ_DATABASE_URL=sqlite:///./var/riskiq.db
RISKIQ_COOKIE_SECURE=false
RISKIQ_AUDIT_KEY=$key
RISKIQ_EMBEDDED_WORKER=true
RISKIQ_BOOTSTRAP_TENANT=demo
RISKIQ_BOOTSTRAP_ADMIN_EMAIL=admin@riskiq.local
RISKIQ_BOOTSTRAP_ADMIN_PASSWORD=$a
RISKIQ_BOOTSTRAP_APPROVER_EMAIL=approver@riskiq.local
RISKIQ_BOOTSTRAP_APPROVER_PASSWORD=$b
RISKIQ_LLM_ENABLED=false
"@ | Set-Content -Encoding utf8 "$root/.env"
@"
LOCAL SECRETS - DO NOT COMMIT
Tenant: demo
Admin: admin@riskiq.local
Password: $a
Reviewer: approver@riskiq.local
Password: $b
"@ | Set-Content -Encoding utf8 "$root/.local-credentials.txt"
Write-Host "Created .env and .local-credentials.txt. Keep both private."
