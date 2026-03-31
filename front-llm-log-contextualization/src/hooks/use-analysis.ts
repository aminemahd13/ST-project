"use client";

import { useCallback, useRef, useState } from "react";
import { AnalysisState, JobStatusResponse, StageSnapshot } from "@/lib/types";
import { fetchJobStatus, submitAnalysis } from "@/lib/api";

const TERMINAL_STATES = new Set(["completed", "partial", "failed"]);
const STAGE_ORDER = ["collector", "preprocessing", "incident", "analysis"];
const MAX_POLL_DURATION_MS = 6 * 60 * 1000;

function buildFallbackStages(status: string): StageSnapshot[] {
  const normalizedStatus = status === "queued" ? "running" : status;
  return STAGE_ORDER.map((stage, index) => {
    if (normalizedStatus === "failed" && stage === "analysis") {
      return {
        stage_name: stage,
        status: "failed",
        attempt: 1,
      };
    }
    if (normalizedStatus === "completed" || normalizedStatus === "partial") {
      return {
        stage_name: stage,
        status: "completed",
        attempt: 1,
      };
    }

    return {
      stage_name: stage,
      status: index === 0 ? "running" : "pending",
      attempt: 1,
    };
  });
}

function mergeStages(response: JobStatusResponse): JobStatusResponse {
  if (response.stages?.length) {
    return response;
  }
  return {
    ...response,
    stages: buildFallbackStages(response.status),
  };
}

export function useAnalysis() {
  const [state, setState] = useState<AnalysisState>({
    file: null,
    forceRefresh: false,
    jobId: null,
    response: null,
    isLoading: false,
    error: null,
  });
  const pollTokenRef = useRef(0);

  const setFile = useCallback((file: File | null) => {
    pollTokenRef.current += 1;
    setState((prev) => ({
      ...prev,
      file,
      jobId: null,
      response: null,
      error: null,
      isLoading: false,
    }));
  }, []);

  const setForceRefresh = useCallback((value: boolean) => {
    setState((prev) => ({
      ...prev,
      forceRefresh: value,
    }));
  }, []);

  const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

  const analyze = useCallback(async () => {
    if (!state.file) return;
    pollTokenRef.current += 1;
    const token = pollTokenRef.current;
    setState((prev) => ({
      ...prev,
      isLoading: true,
      error: null,
      response: null,
      jobId: null,
    }));

    try {
      const submitResult = await submitAnalysis(state.file, { forceRefresh: state.forceRefresh });
      if (token !== pollTokenRef.current) return;
      setState((prev) => ({
        ...prev,
        jobId: submitResult.job_id,
      }));
      const pollStartedAt = Date.now();

      while (token === pollTokenRef.current) {
        if (Date.now() - pollStartedAt > MAX_POLL_DURATION_MS) {
          setState((prev) => ({
            ...prev,
            isLoading: false,
            error:
              "Analysis is taking too long. Check backend logs and verify Hugging Face token/model configuration.",
          }));
          break;
        }

        const response = mergeStages(await fetchJobStatus(submitResult.job_id));
        if (token !== pollTokenRef.current) return;

        const terminal = TERMINAL_STATES.has(response.status);
        const forceRefreshIgnored =
          state.forceRefresh && Boolean(response.deduplicated_from_job_id);
        setState((prev) => ({
          ...prev,
          response,
          isLoading: !terminal,
          error: forceRefreshIgnored
            ? "Force refresh was requested but backend returned cached output. Restart backend with latest code."
            : response.error_message || null,
        }));

        if (terminal) break;
        await sleep(1200);
      }
    } catch (err) {
      if (token !== pollTokenRef.current) return;
      const message = err instanceof Error ? err.message : "An unexpected error occurred";
      setState((prev) => ({ ...prev, error: message, isLoading: false }));
    }
  }, [state.file, state.forceRefresh]);

  const rerun = useCallback(async () => {
    if (!state.file) return;
    await analyze();
  }, [analyze, state.file]);

  const reset = useCallback(() => {
    pollTokenRef.current += 1;
    setState({
      file: null,
      forceRefresh: false,
      jobId: null,
      response: null,
      isLoading: false,
      error: null,
    });
  }, []);

  return {
    ...state,
    setFile,
    setForceRefresh,
    analyze,
    rerun,
    reset,
  };
}
