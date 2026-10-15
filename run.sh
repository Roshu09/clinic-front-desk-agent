#!/usr/bin/env bash
# One command: ./run.sh   ->  API + dashboard on http://localhost:8000
# Optional LLM understanding:  LLM_API_KEY=... LLM_BASE_URL=... LLM_MODEL=... ./run.sh   (see README)
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -q -r backend/requirements.txt
if [ ! -d frontend/dist ]; then
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi
cd backend && exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
