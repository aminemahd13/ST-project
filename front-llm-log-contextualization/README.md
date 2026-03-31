# front-llm-log-contextualization

Next.js frontend for the asynchronous grid-log contextualization platform.

## Features

- PDF upload UI
- Job-based polling flow (`POST /api/analyze` then `GET /api/jobs/{job_id}`)
- Backend pipeline visualization (`collector`, `preprocessing`, `incident`, `analysis`)
- Markdown analysis rendering
- LLM diagnostics panel (provider/model/latency/parse status + raw output preview)
- Export/copy actions for generated report

## Environment

Create `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

## Run

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

## Build

```bash
npm run lint
npm run build
```
