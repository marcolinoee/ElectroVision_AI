"use client";

import { useState } from "react";
import {
  CheckSquare,
  GitBranch,
  MapPin,
  Redo2,
  ScanSearch,
  ShieldCheck,
  Undo2,
} from "lucide-react";
import { BoundingBoxEditor } from "@/components/BoundingBoxEditor";
import { CanvasPlanta } from "@/components/CanvasPlanta";
import { CanvasUnifilar } from "@/components/CanvasUnifilar";
import { ComplianceTable } from "@/components/ComplianceTable";
import { SignOffPanel } from "@/components/SignOffPanel";
import { api } from "@/lib/api";
import { useDigitalTwinStore } from "@/store/useDigitalTwinStore";

type EditorTab = "bboxes" | "unifilar" | "planta" | "compliance" | "signoff";

export default function EditorDigitalTwinPage() {
  const [activeTab, setActiveTab] = useState<EditorTab>("bboxes");
  const [evaluating, setEvaluating] = useState(false);
  const [evalError, setEvalError] = useState<string | null>(null);

  const { status, digitalTwin, complianceReport, setComplianceReport } =
    useDigitalTwinStore();

  const temporal = useDigitalTwinStore.temporal;
  const pendingCount = digitalTwin.components.filter(
    (c) => c.requires_human_review && !c.verified_by_human
  ).length;

  async function runCompliancePreview() {
    setEvalError(null);
    setEvaluating(true);
    try {
      const report = await api.previewCompliance(
        digitalTwin.inspection_id,
        digitalTwin
      );
      setComplianceReport(report);
    } catch (err) {
      setEvalError(
        err instanceof Error
          ? `${err.message} (Verifique se a API local está ativa em localhost:8030)`
          : "Erro ao consultar motor determinístico."
      );
    } finally {
      setEvaluating(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Top Toolbar with Zundo Undo/Redo */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-bold text-slate-900">
              Editor Digital Twin — {digitalTwin.panel.name}
            </h1>
            <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-700">
              {status}
            </span>
          </div>
          <p className="text-xs text-slate-500">
            {pendingCount > 0
              ? `⚠ ${pendingCount} componente(s) com confiança < 0.80 aguardando revisão humana`
              : "✓ Todos os componentes de baixa confiança foram verificados"}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => temporal.getState().undo()}
            className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            title="Desfazer (Zundo Undo)"
          >
            <Undo2 className="h-3.5 w-3.5" />
            Desfazer
          </button>
          <button
            type="button"
            onClick={() => temporal.getState().redo()}
            className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            title="Refazer (Zundo Redo)"
          >
            <Redo2 className="h-3.5 w-3.5" />
            Refazer
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 border-b border-slate-200 pb-2">
        {[
          { id: "bboxes" as const, label: "Bounding Boxes", icon: ScanSearch },
          { id: "unifilar" as const, label: "Diagrama Unifilar", icon: GitBranch },
          { id: "planta" as const, label: "Planta Baixa (DXF)", icon: MapPin },
          { id: "compliance" as const, label: "Conformidade NBR 5410", icon: CheckSquare },
          { id: "signoff" as const, label: "Sign-Off CREA & Export", icon: ShieldCheck },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setActiveTab(id)}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs font-semibold transition ${
              activeTab === id
                ? "bg-blue-600 text-white shadow-sm"
                : "bg-white text-slate-700 hover:bg-slate-100"
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === "bboxes" && <BoundingBoxEditor />}
      {activeTab === "unifilar" && <CanvasUnifilar />}
      {activeTab === "planta" && <CanvasPlanta />}

      {activeTab === "compliance" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-600">
              Motor determinístico NBR 5410 / NR-10 / NBR 14039 (independente de RAG/LLM).
            </p>
            <button
              type="button"
              disabled={evaluating}
              onClick={runCompliancePreview}
              className="rounded-md bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:bg-slate-300"
            >
              {evaluating
                ? "Calculando..."
                : "Avaliar Conformidade (NBR 5410 / NR-10)"}
            </button>
          </div>
          {evalError && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {evalError}
            </div>
          )}
          <ComplianceTable report={complianceReport} />
        </div>
      )}

      {activeTab === "signoff" && <SignOffPanel />}
    </div>
  );
}
