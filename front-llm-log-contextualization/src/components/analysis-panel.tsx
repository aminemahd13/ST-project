"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { FileSearch } from "lucide-react";
import { AnalysisPayload, JobStatusResponse, LlmTrace } from "@/lib/types";

interface AnalysisPanelProps {
  response: JobStatusResponse | null;
  isLoading: boolean;
  error: string | null;
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4 p-1">
      <Skeleton className="h-6 w-3/4" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-4/5" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-4 w-3/4" />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="rounded-full bg-muted p-4">
        <FileSearch className="h-8 w-8 text-muted-foreground" />
      </div>
      <div>
        <h3 className="text-lg font-medium">No analysis yet</h3>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          Upload a PDF and start analysis to get incident contextualization and backend stage visibility.
        </p>
      </div>
    </div>
  );
}

export function AnalysisPanel({ response, isLoading, error }: AnalysisPanelProps) {
  if (error && !response) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
        <div className="rounded-full bg-destructive/10 p-4">
          <span className="text-2xl">!</span>
        </div>
        <div>
          <h3 className="text-lg font-medium text-destructive">Analysis Failed</h3>
          <p className="mt-1 max-w-md text-sm text-muted-foreground">{error}</p>
        </div>
      </div>
    );
  }

  if (isLoading && !response) {
    return <LoadingSkeleton />;
  }

  if (!response) {
    return <EmptyState />;
  }

  const diagnostics = extractLlmDiagnostics(response);
  const reasoning = diagnostics.analysis?.reasoning_summary || [];
  const stageError = response.stages.find(
    (stage) => stage.stage_name === "analysis" && stage.status === "failed"
  )?.error_message;
  const failed = response.status === "failed";
  const running = response.status === "running" || response.status === "queued";
  const effectiveError = response.error_message || stageError || error;
  const markdown = resolveMarkdown({
    raw: response.analysis,
    failed,
    running,
    effectiveError,
  });

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-2 border-b pb-3">
        <Badge variant="outline" className="text-xs">
          {response.model}
        </Badge>
        <Badge variant={response.status === "failed" ? "destructive" : "secondary"} className="text-xs capitalize">
          {response.status}
        </Badge>
        <span className="text-xs text-muted-foreground">
          {new Date(response.updated_at).toLocaleString()}
        </span>
      </div>
      <ScrollArea className="flex-1">
        <div className="prose prose-sm dark:prose-invert max-w-none pr-4">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
        </div>

        <div className="mt-6 rounded-md border p-3 text-sm">
          <h4 className="mb-2 text-sm font-semibold">LLM Diagnostics</h4>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">{`provider: ${diagnostics.trace?.provider || "n/a"}`}</Badge>
            <Badge variant="outline">{`model: ${diagnostics.trace?.model || "n/a"}`}</Badge>
            <Badge variant="outline">{`prompt: ${diagnostics.trace?.prompt_version || "n/a"}`}</Badge>
            <Badge variant="outline">{`latency: ${diagnostics.trace?.latency_ms ?? "n/a"} ms`}</Badge>
            <Badge variant="outline">{`chars: ${diagnostics.trace?.response_chars ?? 0}`}</Badge>
            <Badge
              variant={
                !diagnostics.trace ? "outline" : diagnostics.trace.parse_ok ? "secondary" : "destructive"
              }
            >
              {!diagnostics.trace
                ? "JSON status: waiting"
                : diagnostics.trace.parse_ok
                  ? "JSON parsed"
                  : "JSON parse failed"}
            </Badge>
          </div>

          {stageError && (
            <p className="mt-3 text-xs text-destructive">
              {`analysis stage error: ${stageError}`}
            </p>
          )}
          {diagnostics.trace?.request_error && (
            <p className="mt-1 text-xs text-destructive">
              {`llm request error: ${diagnostics.trace.request_error}`}
            </p>
          )}
          {!diagnostics.trace && running && (
            <p className="mt-1 text-xs text-muted-foreground">
              Waiting for analysis stage output...
            </p>
          )}
          {!diagnostics.trace && failed && (
            <p className="mt-1 text-xs text-destructive">
              No LLM diagnostics were returned for this failed job.
            </p>
          )}

          {reasoning.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Reasoning Summary
              </p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">
                {reasoning.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          {diagnostics.trace?.raw_output_preview && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                Raw LLM output preview
              </summary>
              <pre className="mt-2 overflow-x-auto rounded bg-muted p-2 text-[11px] leading-relaxed">
                {diagnostics.trace.raw_output_preview}
              </pre>
            </details>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

function extractLlmDiagnostics(response: JobStatusResponse): {
  analysis: AnalysisPayload | null;
  trace: LlmTrace | null;
} {
  const analysisStage = response.pipeline?.analysis;
  const analysis = analysisStage?.analysis || null;
  const failedAnalysisStage = response.stages.find(
    (stage) => stage.stage_name === "analysis" && stage.status === "failed"
  );
  const stageTrace = (failedAnalysisStage?.payload as { llm_trace?: LlmTrace } | undefined)?.llm_trace;
  const trace = analysis?.llm_trace || stageTrace || null;
  return { analysis, trace };
}

function resolveMarkdown({
  raw,
  failed,
  running,
  effectiveError,
}: {
  raw?: string | null;
  failed: boolean;
  running: boolean;
  effectiveError?: string | null;
}): string {
  if (raw?.trim()) {
    return raw;
  }
  if (failed) {
    return `# Analysis failed\n\n${effectiveError || "The analysis stage failed before producing a report."}`;
  }
  if (running) {
    return "# Analysis in progress\n\nThe backend is currently processing the analysis stage.";
  }
  return "# Analysis pending\n\nNo report has been produced yet.";
}
