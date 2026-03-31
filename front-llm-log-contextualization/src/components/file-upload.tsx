"use client";

import { useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { Upload, File as FileIcon, X } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatFileSize } from "@/lib/export-utils";

interface FileUploadProps {
  file: File | null;
  forceRefresh: boolean;
  onFileSelect: (file: File | null) => void;
  onForceRefreshChange: (value: boolean) => void;
  onAnalyze: () => void;
  isLoading: boolean;
}

export function FileUpload({
  file,
  forceRefresh,
  onFileSelect,
  onForceRefreshChange,
  onAnalyze,
  isLoading,
}: FileUploadProps) {
  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      if (acceptedFiles.length > 0) {
        onFileSelect(acceptedFiles[0]);
      }
    },
    [onFileSelect]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: false,
    accept: {
      "application/pdf": [".pdf"],
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <div
        {...getRootProps()}
        className={`group relative cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
          isDragActive
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25 hover:border-primary/50 hover:bg-muted/50"
        }`}
      >
        <input {...getInputProps()} />
        <div className="flex flex-col items-center gap-3">
          <div className="rounded-full bg-muted p-3">
            <Upload className="h-6 w-6 text-muted-foreground" />
          </div>
          {isDragActive ? (
            <p className="text-sm font-medium text-primary">Drop the file here</p>
          ) : (
            <>
              <p className="text-sm font-medium">
                Drag & drop a file here, or click to browse
              </p>
              <p className="text-xs text-muted-foreground">
                PDF only (operational synthesis notices).
              </p>
            </>
          )}
        </div>
      </div>

      {file && (
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="rounded-md bg-muted p-2">
              <FileIcon className="h-5 w-5 text-muted-foreground" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="truncate text-sm font-medium">{file.name}</p>
              <div className="flex items-center gap-2 mt-1">
                <Badge variant="secondary" className="text-xs">
                  {file.type || "unknown"}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {formatFileSize(file.size)}
                </span>
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0"
              onClick={(e) => {
                e.stopPropagation();
                onFileSelect(null);
              }}
              aria-label="Remove file"
            >
              <X className="h-4 w-4" />
            </Button>
          </CardContent>
        </Card>
      )}

      <Button
        type="button"
        variant={forceRefresh ? "secondary" : "outline"}
        onClick={() => onForceRefreshChange(!forceRefresh)}
        disabled={isLoading}
      >
        {forceRefresh ? "Force Refresh: On (Ignore Cache)" : "Force Refresh: Off (Use Cache)"}
      </Button>

      <Button
        onClick={onAnalyze}
        disabled={!file || isLoading}
        className="w-full"
        size="lg"
      >
        {isLoading ? (
          <>
            <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            Analyzing...
          </>
        ) : (
          "Analyze File"
        )}
      </Button>
    </div>
  );
}

