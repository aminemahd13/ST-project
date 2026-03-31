# Operational Runbook

## Startup Checks

1. Verify PostgreSQL connectivity (`GRID_APP_DATABASE_URL`).
2. Verify writable `GRID_APP_STORAGE_DIR`.
3. Verify `GRID_APP_RAG_SEED_DIR` exists for context indexing.
4. Verify LLM provider config:
   - `GRID_APP_LLM_PROVIDER=huggingface` requires `GRID_APP_HF_TOKEN`.
   - `GRID_APP_LLM_PROVIDER=ollama` requires reachable `GRID_APP_OLLAMA_BASE_URL`.
   - `GRID_APP_LLM_PROVIDER=auto` uses Hugging Face first, then Ollama.
5. For Docker + Ollama runs, verify `ollama` and `ollama-pull` services completed successfully (`--profile ollama`).
6. For Docker runs, prefer `GRID_APP_DATABASE_URL_DOCKER` / `GRID_APP_OLLAMA_BASE_URL_DOCKER` overrides instead of local `localhost` values.

## Health and Monitoring

- Health: `GET /api/health`
- Metrics: `GET /metrics`
- Job diagnostics: `GET /api/jobs/{job_id}`

## Failure Triage

1. If job status is `failed`, inspect `error_message` in job payload.
2. Check stage-level failure from `stages[]`.
3. Validate PDF signature and upload size limits.
4. Verify database and filesystem write permissions.
5. If LLM fails, inspect `stages[].payload.llm_trace` for provider/model/error details (no deterministic fallback is used).

## Security Controls

- Enable `GRID_APP_API_KEY` for API access control.
- Configure strict CORS origins with `GRID_APP_CORS_ALLOW_ORIGINS`.
- Tune `GRID_APP_RATE_LIMIT_REQUESTS_PER_MINUTE`.
