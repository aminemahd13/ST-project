export type JobStatus = "queued" | "running" | "completed" | "partial" | "failed";
export type StageStatus = "pending" | "running" | "completed" | "failed";

export interface StageSnapshot {
  stage_name: "collector" | "preprocessing" | "incident" | "analysis" | string;
  status: StageStatus | string;
  attempt: number;
  error_message?: string | null;
  payload?: Record<string, unknown> | null;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
}

export interface JobSubmissionResponse {
  job_id: string;
  status: JobStatus;
  status_url: string;
  deduplicated: boolean;
  force_refresh_applied?: boolean;
  created_at: string;
}

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  filename: string;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  deduplicated_from_job_id?: string | null;
  error_message?: string | null;
  analysis?: string | null;
  model: string;
  pipeline?: PipelineResultPayload | null;
  stages: StageSnapshot[];
}

export interface LlmTrace {
  provider?: string;
  model?: string;
  latency_ms?: number;
  response_chars?: number;
  prompt_version?: string;
  request_error?: string | null;
  parse_ok?: boolean;
  prompt_incident_count?: number;
  prompt_rag_sources?: string[];
  raw_output_preview?: string | null;
}

export interface AnalysisPayload {
  executive_summary?: string;
  recommended_actions?: string[];
  cross_incident_insights?: string[];
  reasoning_summary?: string[];
  llm_model?: string;
  llm_provider?: string;
  llm_trace?: LlmTrace;
}

export interface AnalysisStagePayload {
  document_id?: string;
  analysis?: AnalysisPayload;
  human_summary?: string;
}

export interface PipelineResultPayload {
  document_id?: string | null;
  status?: string;
  collector?: Record<string, unknown> | null;
  preprocessing?: Record<string, unknown> | null;
  incident?: Record<string, unknown> | null;
  analysis?: AnalysisStagePayload | null;
  errors?: string[];
}

export interface ApiError {
  error?: string;
  message?: string;
  detail?: string;
}

export interface AnalysisState {
  file: File | null;
  forceRefresh: boolean;
  jobId: string | null;
  response: JobStatusResponse | null;
  isLoading: boolean;
  error: string | null;
}
