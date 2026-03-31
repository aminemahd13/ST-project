"use client";

import { CheckCircle2, Circle, Clock3, XCircle } from "lucide-react";
import { StageSnapshot } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

interface PipelineTimelineProps {
  stages: StageSnapshot[];
  jobStatus: string | null;
}

const LABELS: Record<string, string> = {
  collector: "Collector",
  preprocessing: "Preprocessing",
  incident: "Incident",
  analysis: "Analysis",
};

function normalizeStages(stages: StageSnapshot[]): StageSnapshot[] {
  const order = ["collector", "preprocessing", "incident", "analysis"];
  const byName = new Map(stages.map((stage) => [stage.stage_name, stage]));
  return order.map((name) => {
    const found = byName.get(name);
    if (found) return found;
    return {
      stage_name: name,
      status: "pending",
      attempt: 1,
    };
  });
}

function iconForStatus(status: string) {
  if (status === "completed") return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === "running") return <Clock3 className="h-4 w-4 text-blue-500 animate-pulse" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-destructive" />;
  return <Circle className="h-4 w-4 text-muted-foreground/60" />;
}

function badgeVariant(status: string): "secondary" | "destructive" | "outline" {
  if (status === "failed") return "destructive";
  if (status === "completed") return "secondary";
  return "outline";
}

export function PipelineTimeline({ stages, jobStatus }: PipelineTimelineProps) {
  const normalized = normalizeStages(stages || []);
  return (
    <div className="rounded-lg border bg-card/40 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold tracking-wide">Backend Pipeline</h3>
        <Badge variant={jobStatus === "failed" ? "destructive" : "outline"} className="capitalize">
          {jobStatus || "idle"}
        </Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {normalized.map((stage) => (
          <div
            key={stage.stage_name}
            className="rounded-md border px-3 py-2"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {iconForStatus(stage.status)}
                <span className="text-sm font-medium">{LABELS[stage.stage_name] || stage.stage_name}</span>
              </div>
              <Badge variant={badgeVariant(stage.status)} className="capitalize">
                {stage.status}
              </Badge>
            </div>
            {stage.error_message && (
              <p className="mt-1 truncate text-xs text-destructive" title={stage.error_message}>
                {stage.error_message}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
