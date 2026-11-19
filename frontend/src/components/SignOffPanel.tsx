"use client";

import { useState } from "react";
import { CheckCircle2, Download, FileCheck2, Lock, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useDigitalTwinStore } from "@/store/useDigitalTwinStore";
import type { ArtifactType } from "@/types/digitalTwin";
import { JobProgressSSE } from "@/components/JobProgressSSE";

export function SignOffPanel() {
  const {
    status,
    digitalTwin,
    signedSha256,
    validatedByName,
    validatedByCrea,
    artNumber,
    markSignedOff,
    markExported,
  } = useDigitalTwinStore();

  const [engineerName, setEngineerName] = useState(validatedByName || "");
  const [engineerCrea, setEngineerCrea] = useState(validatedByCrea || "");
  const [artInput, setArtInput] = useState(artNumber || "");
  const [confirmedResponsibility, setConfirmedResponsibility] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [exportJobId, setExportJobId] = useState<string | null>(null);

  const pendingReview = digitalTwin.components.filter(
    (c) => c.requires_human_review && !c.verified_by_human
  );
  const canSignOff =
    pendingReview.length === 0 &&
    engineerName.trim().length >= 3 &&
    engineerCrea.trim().length >= 4 &&
    confirmedResponsibility;

  const canExport = status === "ENGINEER_VALIDATED" || status === "EXPORTED";

  async function handleSignOff() {
    setErrorMsg(null);
    setSubmitting(true);
    try {
      const resp = await api.signOffInspection(
        digitalTwin.inspection_id,
        {
          engineer_name: engineerName.trim(),
          engineer_crea: engineerCrea.trim().toUpperCase(),
          art_number: artInput.trim() || undefined,
        },
        digitalTwin
      );
      markSignedOff({
        sha256: resp.digital_twin_sha256,
        engineerName: resp.validated_by_name,
        engineerCrea: resp.validated_by_crea,
        artNumber: resp.art_number,
      });
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Não foi possível registrar o Sign-Off no servidor."
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleOfficialExport(artifacts: ArtifactType[]) {
    setErrorMsg(null);
    try {
      const dispatch = await api.dispatchExport(digitalTwin.inspection_id, artifacts);
      setExportJobId(dispatch.job_id);
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : "Falha ao despachar exportação oficial."
      );
    }
  }

  return (
    <div className="space-y-6">
      {/* Status Banner */}
      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-blue-600" />
            <h2 className="text-base font-bold text-slate-900">
              Sign-Off Obrigatório do Engenheiro (CREA / ART)
            </h2>
          </div>
          <span
            className={`rounded-full px-3 py-1 text-xs font-bold ${
              status === "ENGINEER_VALIDATED" || status === "EXPORTED"
                ? "bg-emerald-100 text-emerald-800"
                : "bg-amber-100 text-amber-800"
            }`}
          >
            Estado Atual: {status}
          </span>
        </div>

        <p className="mt-2 text-xs text-slate-600">
          Máquina de estados rígida: <code>DRAFT → AI_PROCESSED → ENGINEER_VALIDATED → EXPORTED</code>.
          É estritamente proibido exportar laudos oficiais (.DXF, .DOCX, .XLSX) sem validação humana e
          assinatura criptográfica SHA-256 do <code>DigitalTwinJSON</code>.
        </p>

        {pendingReview.length > 0 && (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-800">
            <strong>Bloqueio de Segurança:</strong> Existem{" "}
            <strong>{pendingReview.length}</strong> componente(s) com confiança &lt; 0.80 ainda não
            verificados pelo engenheiro ({pendingReview.map((c) => c.label).join(", ")}). Revise-os
            na aba <em>Bounding Boxes</em> antes de assinar.
          </div>
        )}

        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700">
              Nome do Engenheiro Eletricista *
            </label>
            <input
              type="text"
              value={engineerName}
              onChange={(e) => setEngineerName(e.target.value)}
              placeholder="Eng. Maria Silva"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700">
              Registro CREA *
            </label>
            <input
              type="text"
              value={engineerCrea}
              onChange={(e) => setEngineerCrea(e.target.value)}
              placeholder="CREA-SP 5061234567"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm uppercase focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700">
              Número da ART (opcional)
            </label>
            <input
              type="text"
              value={artInput}
              onChange={(e) => setArtInput(e.target.value)}
              placeholder="ART-2026-000123"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
        </div>

        <label className="mt-4 flex items-start gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            checked={confirmedResponsibility}
            onChange={(e) => setConfirmedResponsibility(e.target.checked)}
            className="mt-0.5 rounded border-slate-300"
          />
          <span>
            Declaro ter revisado presencialmente/tecnicamente todas as detecções, leituras OCR,
            circuitos e não-conformidades do Digital Twin, assumindo responsabilidade técnica perante
            o CREA/CONFEA.
          </span>
        </label>

        {errorMsg && (
          <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {errorMsg}
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={!canSignOff || submitting}
            onClick={handleSignOff}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            <FileCheck2 className="h-4 w-4" />
            {submitting ? "Registrando Sign-Off..." : "Validar e Assinar DigitalTwin (SHA-256)"}
          </button>

          {signedSha256 && (
            <div className="flex items-center gap-1.5 rounded-md bg-emerald-50 px-3 py-1.5 font-mono text-xs text-emerald-800">
              <CheckCircle2 className="h-4 w-4" />
              SHA-256: {signedSha256.slice(0, 16)}...
            </div>
          )}
        </div>
      </div>

      {/* Official Export Section */}
      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          {canExport ? (
            <Download className="h-5 w-5 text-emerald-600" />
          ) : (
            <Lock className="h-5 w-5 text-slate-400" />
          )}
          <h3 className="text-sm font-bold text-slate-900">
            Exportação de Artefatos Oficiais Auditados (Worker Engine)
          </h3>
        </div>
        <p className="mt-1 text-xs text-slate-600">
          Todo <code>.DXF</code> passa por <code>ezdxf.audit()</code> sem erros e recebe vínculo
          SHA-256 no <code>export_manifest.json</code>.
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!canExport}
            onClick={() =>
              handleOfficialExport([
                "UNIFILAR_DXF",
                "UNIFILAR_SVG",
                "MEMORIAL_DOCX",
                "RETROFIT_XLSX",
              ])
            }
            className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500"
          >
            <Download className="h-4 w-4" />
            Exportar Pacote Completo (Unifilar DXF/SVG + Memorial DOCX + Planilha SINAPI XLSX)
          </button>

          <button
            type="button"
            disabled={!canExport || !digitalTwin.spatial_calibration?.calibrated_by_human}
            onClick={() => handleOfficialExport(["PLANTA_DXF"])}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Exportar Planta Elétrica (.DXF sobre Base Calibrada)
          </button>
        </div>

        {exportJobId && (
          <div className="mt-4">
            <JobProgressSSE
              jobId={exportJobId}
              title="Exportação Oficial (engine_queue)"
              onCompleted={() => markExported()}
            />
          </div>
        )}
      </div>
    </div>
  );
}
