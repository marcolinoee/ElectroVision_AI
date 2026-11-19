"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { API_BASE_URL } from "@/lib/api";
import type { JobProgressEvent } from "@/types/digitalTwin";

interface JobProgressSSEProps {
  jobId: string | null;
  title?: string;
  onCompleted?: (event: JobProgressEvent) => void;
  onFailed?: (event: JobProgressEvent) => void;
}

export function JobProgressSSE({
  jobId,
  title = "Progresso do Job Celery",
  onCompleted,
  onFailed,
}: JobProgressSSEProps) {
  const [events, setEvents] = useState<JobProgressEvent[]>([]);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    setEvents([]);
    setConnectionError(null);

    const url = `${API_BASE_URL}/api/v1/events/jobs/${encodeURIComponent(jobId)}`;
    const source = new EventSource(url);

    const handleEvent = (raw: MessageEvent) => {
      try {
        const parsed: JobProgressEvent = JSON.parse(raw.data);
        setEvents((prev) => [...prev, parsed]);
        if (parsed.status === "COMPLETED") {
          source.close();
          onCompleted?.(parsed);
        } else if (parsed.status === "FAILED") {
          source.close();
          onFailed?.(parsed);
        }
      } catch {
        // Ignore non-JSON keepalive frames
      }
    };

    source.addEventListener("started", handleEvent);
    source.addEventListener("progress", handleEvent);
    source.addEventListener("completed", handleEvent);
    source.addEventListener("failed", handleEvent);
    source.onmessage = handleEvent;

    source.onerror = () => {
      setConnectionError("Conexão SSE interrompida ou encerrada.");
      source.close();
    };

    return () => {
      source.close();
    };
  }, [jobId, onCompleted, onFailed]);

  if (!jobId) return null;

  const latest = events[events.length - 1];
  const pct = latest?.progress_pct ?? 5;
  const status = latest?.status ?? "STARTED";

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {status === "COMPLETED" ? (
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
          ) : status === "FAILED" ? (
            <AlertCircle className="h-5 w-5 text-red-600" />
          ) : (
            <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
          )}
          <span className="text-sm font-semibold text-slate-900">{title}</span>
        </div>
        <span className="font-mono text-xs text-slate-500">
          {status} • {pct}%
        </span>
      </div>

      <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full transition-all duration-300 ${
            status === "FAILED"
              ? "bg-red-500"
              : status === "COMPLETED"
              ? "bg-emerald-500"
              : "bg-blue-600"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <p className="mt-2 text-xs text-slate-600">
        {latest?.message || `Aguardando eventos SSE para o job ${jobId}...`}
      </p>

      {connectionError && status !== "COMPLETED" && status !== "FAILED" && (
        <p className="mt-1 text-xs text-amber-600">{connectionError}</p>
      )}
    </div>
  );
}
