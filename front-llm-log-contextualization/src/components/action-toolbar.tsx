"use client";

import {
  RefreshCw,
  Copy,
  Download,
  FileText,
  FileDown,
  Printer,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import { JobStatusResponse } from "@/lib/types";
import { copyToClipboard, exportAsMarkdown, exportAsText } from "@/lib/export-utils";

interface ActionToolbarProps {
  response: JobStatusResponse | null;
  isLoading: boolean;
  onRerun: () => void;
}

export function ActionToolbar({ response, isLoading, onRerun }: ActionToolbarProps) {
  const markdown = response?.analysis?.trim() || "";
  const disabled = !response || isLoading;
  const exportDisabled = !markdown;
  const baseFilename = response?.filename?.replace(/\.[^/.]+$/, "") ?? "analysis";

  const handleCopy = async () => {
    if (!markdown) return;
    try {
      await copyToClipboard(markdown);
      toast.success("Copied to clipboard", {
        description: "Markdown content copied successfully.",
      });
    } catch {
      toast.error("Failed to copy", {
        description: "Could not access the clipboard.",
      });
    }
  };

  const handleExportMd = () => {
    if (!markdown) return;
    exportAsMarkdown(markdown, baseFilename);
    toast.success("Exported", { description: `${baseFilename}-analysis.md downloaded.` });
  };

  const handleExportTxt = () => {
    if (!markdown) return;
    exportAsText(markdown, baseFilename);
    toast.success("Exported", { description: `${baseFilename}-analysis.txt downloaded.` });
  };

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={onRerun}
        disabled={disabled}
        title="Re-analyze the same file"
      >
        <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
        Re-run
      </Button>

      <Button
        variant="outline"
        size="sm"
        onClick={handleCopy}
        disabled={disabled || exportDisabled}
        title="Copy analysis as Markdown"
      >
        <Copy className="mr-1.5 h-3.5 w-3.5" />
        Copy MD
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger
          disabled={disabled || exportDisabled}
          className="inline-flex h-8 items-center justify-center gap-2 whitespace-nowrap rounded-md border border-input bg-background px-3 text-sm font-medium shadow-xs transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
        >
          <Download className="mr-1.5 h-3.5 w-3.5" />
          Export
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={handleExportMd}>
            <FileText className="mr-2 h-4 w-4" />
            Export as Markdown (.md)
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleExportTxt}>
            <FileDown className="mr-2 h-4 w-4" />
            Export as Plain Text (.txt)
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handlePrint}>
            <Printer className="mr-2 h-4 w-4" />
            Print / Save as PDF
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
