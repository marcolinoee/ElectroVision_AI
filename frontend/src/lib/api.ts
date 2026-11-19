import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type {
  ArtifactType,
  ComplianceReport,
  DigitalTwinJSON,
  InspectionSummary,
  JobDispatchResponse,
  ModelVersionSummary,
  ProjectSummary,
} from "@/types/digitalTwin";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8030";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10000);
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: init?.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers || {}),
      },
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        detail = body.detail || JSON.stringify(body);
      } catch {
        // keep status text
      }
      throw new Error(detail);
    }
    return res.json() as Promise<T>;
  } finally {
    clearTimeout(timeoutId);
  }
}

export const api = {
  listProjects: () => requestJson<ProjectSummary[]>("/api/v1/projects"),

  createProject: (payload: {
    name: string;
    client_name: string;
    address?: string;
    installation_type?: string;
    supply_system: string;
    grounding_scheme: string;
    nominal_voltage_v: number;
    engineer_name?: string;
    engineer_crea?: string;
  }) =>
    requestJson<ProjectSummary>("/api/v1/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  createInspection: (project_id: string, title: string) =>
    requestJson<InspectionSummary>("/api/v1/inspections", {
      method: "POST",
      body: JSON.stringify({ project_id, title }),
    }),

  listInspections: () => requestJson<InspectionSummary[]>("/api/v1/inspections"),

  getInspection: (inspectionId: string) =>
    requestJson<InspectionSummary>(`/api/v1/inspections/${inspectionId}`),

  uploadInspectionMedia: async (inspectionId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(
      `${API_BASE_URL}/api/v1/inspections/${inspectionId}/upload-media`,
      { method: "POST", body: form }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Falha no upload de mídia.");
    }
    return res.json();
  },

  uploadProjectBaseDxf: async (projectId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(
      `${API_BASE_URL}/api/v1/projects/${projectId}/upload-dxf`,
      { method: "POST", body: form }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Falha no upload do DXF base.");
    }
    return res.json();
  },

  dispatchInference: (inspectionId: string) =>
    requestJson<JobDispatchResponse>(
      `/api/v1/inspections/${inspectionId}/infer`,
      { method: "POST" }
    ),

  previewCompliance: (_inspectionId: string, digitalTwin: DigitalTwinJSON) =>
    requestJson<ComplianceReport>("/api/v1/compliance/preview", {
      method: "POST",
      body: JSON.stringify(digitalTwin),
    }),

  signOffInspection: (
    inspectionId: string,
    credentials: {
      engineer_name: string;
      engineer_crea: string;
      art_number?: string;
    },
    digital_twin: DigitalTwinJSON
  ) =>
    requestJson<{
      inspection_id: string;
      status: string;
      digital_twin_sha256: string;
      validated_by_name: string;
      validated_by_crea: string;
      art_number?: string | null;
      validated_at: string;
    }>(`/api/v1/inspections/${inspectionId}/sign-off`, {
      method: "POST",
      body: JSON.stringify({ credentials, digital_twin }),
    }),

  dispatchExport: (inspectionId: string, artifacts: ArtifactType[]) =>
    requestJson<JobDispatchResponse>(
      `/api/v1/inspections/${inspectionId}/export`,
      {
        method: "POST",
        body: JSON.stringify({ artifacts }),
      }
    ),

  listModels: () => requestJson<ModelVersionSummary[]>("/api/v1/ml/models"),

  dispatchTraining: (epochs: number, replay_ratio: number) =>
    requestJson<JobDispatchResponse>("/api/v1/ml/train", {
      method: "POST",
      body: JSON.stringify({ epochs, replay_ratio }),
    }),

  startHarvest: (max_mb: number, sources?: string[], max_items_per_source?: number) =>
    requestJson<JobDispatchResponse>("/api/v1/ml/harvest/start", {
      method: "POST",
      body: JSON.stringify({
        max_mb,
        sources: sources ?? ["wikimedia", "huggingface", "public_yolo", "cad_symbols"],
        max_items_per_source: max_items_per_source ?? 1500,
      }),
    }),

  importNormPdf: async (standardCode: string, file: File) => {
    const form = new FormData();
    form.append("standard_code", standardCode);
    form.append("file", file);
    const res = await fetch(`${API_BASE_URL}/api/v1/norms/import-pdf`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Falha ao importar PDF normativo.");
    }
    return res.json();
  },
};
