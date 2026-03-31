# Architecture

```mermaid
flowchart LR
  UI[Next.js Frontend] -->|POST /api/analyze| API[FastAPI API]
  UI -->|GET /api/jobs/{job_id}| API

  API --> DB[(PostgreSQL)]
  API --> FS[(Durable Storage)]
  API --> Worker[Async Job Processor]

  Worker --> Collector[Collector Agent]
  Worker --> Preproc[Preprocessing Agent]
  Worker --> Incident[Incident Agent]
  Worker --> Analysis[Analysis Agent]

  Analysis --> Groq[Groq LLM]
  Analysis --> RAG[Retriever]
  RAG --> SeedPDFs[(Historical PDFs)]
```

## Data Flow

1. Client uploads PDF -> API validates type/size/signature.
2. API stores file, creates job row, and schedules async processing.
3. Worker executes pipeline stages and persists stage updates.
4. Analysis stage merges deterministic statistics + LLM/RAG enrichment.
5. Frontend polls job endpoint and renders stage timeline + markdown report.
