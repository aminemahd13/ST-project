"use client";

import { Header } from "@/components/header";
import { FileUpload } from "@/components/file-upload";
import { AnalysisPanel } from "@/components/analysis-panel";
import { ActionToolbar } from "@/components/action-toolbar";
import { PipelineTimeline } from "@/components/pipeline-timeline";
import { useAnalysis } from "@/hooks/use-analysis";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export default function DashboardPage() {
  const {
    file,
    forceRefresh,
    jobId,
    response,
    isLoading,
    error,
    setFile,
    setForceRefresh,
    analyze,
    rerun,
    reset,
  } = useAnalysis();

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header />

      <main className="flex-1 p-4 md:p-6">
        <div className="mx-auto grid h-full max-w-7xl gap-6 md:grid-cols-[380px_1fr]">
          <div className="flex flex-col gap-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Upload File</CardTitle>
              </CardHeader>
              <CardContent>
                <FileUpload
                  file={file}
                  forceRefresh={forceRefresh}
                  onFileSelect={setFile}
                  onForceRefreshChange={setForceRefresh}
                  onAnalyze={analyze}
                  isLoading={isLoading}
                />
              </CardContent>
            </Card>

            {(response || error) && (
              <button
                onClick={reset}
                className="self-center text-xs text-muted-foreground underline-offset-4 hover:underline"
              >
                Clear &amp; start over
              </button>
            )}
          </div>

          <div className="flex min-h-[60vh] flex-col gap-4">
            <Card>
              <CardContent className="pt-4">
                <PipelineTimeline
                  stages={response?.stages || []}
                  jobStatus={response?.status || (isLoading ? "running" : null)}
                />
                {jobId && (
                  <p className="mt-2 text-xs text-muted-foreground">Job ID: {jobId}</p>
                )}
              </CardContent>
            </Card>

            <Card className="flex flex-1 flex-col">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
                <CardTitle className="text-base">Analysis Report</CardTitle>
                <ActionToolbar response={response} isLoading={isLoading} onRerun={rerun} />
              </CardHeader>
              <Separator />
              <CardContent className="flex-1 pt-4">
                <AnalysisPanel response={response} isLoading={isLoading} error={error} />
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  );
}
