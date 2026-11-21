# Starts the LegalAI API on port 8000.
# 0.0.0.0 = reachable from Docker (the Anti-Firibgar web app) and from your backend on another machine.
# Requests without the X-API-Key from .env are rejected; set ALLOWED_IPS in .env to also limit by IP.
# Ollama must be running. Stop with Ctrl+C.
Set-Location $PSScriptRoot
python -m uvicorn server:app --host 0.0.0.0 --port 8000
