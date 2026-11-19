"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { UploadCloud, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { JobProgressSSE } from "@/components/JobProgressSSE";

export default function NewProjectPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [clientName, setClientName] = useState("");
  const [supplySystem, setSupplySystem] = useState("BIFASICO_127_220V");
  const [groundingScheme, setGroundingScheme] = useState("TN_S");
  const [nominalVoltage, setNominalVoltage] = useState(220);
  const [inspectionTitle, setInspectionTitle] = useState("QDC Principal");
  const [mediaFile, setMediaFile] = useState<File | null>(null);
  const [dxfFile, setDxfFile] = useState<File | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrorMsg(null);
    setSubmitting(true);
    try {
      const project = await api.createProject({
        name: name.trim(),
        client_name: clientName.trim(),
        supply_system: supplySystem,
        grounding_scheme: groundingScheme,
        nominal_voltage_v: nominalVoltage,
      });

      if (dxfFile) {
        await api.uploadProjectBaseDxf(project.id, dxfFile);
      }

      const inspection = await api.createInspection(project.id, inspectionTitle.trim());

      if (mediaFile) {
        await api.uploadInspectionMedia(inspection.id, mediaFile);
        const dispatch = await api.dispatchInference(inspection.id);
        setJobId(dispatch.job_id);
      } else {
        router.push("/editor");
      }
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Erro ao criar projeto.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Novo Projeto &amp; Inspeção Diagnóstica</h1>
        <p className="text-sm text-slate-600">
          Cadastre a instalação, envie foto/vídeo do quadro (validado por magic bytes) e opcionalmente
          o arquivo .DXF arquitetônico base.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-xs font-semibold text-slate-700">Nome do Projeto *</label>
            <input
              required
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Retrofit QDC Edifício Paulista"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700">Cliente *</label>
            <input
              required
              type="text"
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
              placeholder="Condomínio Paulista"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700">Fornecimento</label>
            <select
              value={supplySystem}
              onChange={(e) => setSupplySystem(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="MONOFASICO_127V">Monofásico 127V</option>
              <option value="MONOFASICO_220V">Monofásico 220V</option>
              <option value="BIFASICO_127_220V">Bifásico 127/220V</option>
              <option value="TRIFASICO_220_127V">Trifásico 220/127V</option>
              <option value="TRIFASICO_380_220V">Trifásico 380/220V</option>
              <option value="MEDIA_TENSAO_13_8KV">Média Tensão 13.8kV</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700">Aterramento</label>
            <select
              value={groundingScheme}
              onChange={(e) => setGroundingScheme(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="TN_S">TN-S</option>
              <option value="TN_C_S">TN-C-S</option>
              <option value="TN_C">TN-C</option>
              <option value="TT">TT</option>
              <option value="IT">IT</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700">Tensão Nominal (V)</label>
            <input
              type="number"
              value={nominalVoltage}
              onChange={(e) => setNominalVoltage(Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700">
            Identificação do Quadro / Inspeção
          </label>
          <input
            type="text"
            value={inspectionTitle}
            onChange={(e) => setInspectionTitle(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="rounded-md border border-dashed border-slate-300 p-3">
            <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-700">
              <UploadCloud className="h-4 w-4 text-blue-600" />
              Foto ou Vídeo do Quadro (JPG/PNG/MP4)
            </label>
            <input
              type="file"
              accept=".jpg,.jpeg,.png,.webp,.mp4,.mov,.avi,.mkv"
              onChange={(e) => setMediaFile(e.target.files?.[0] ?? null)}
              className="mt-2 block w-full text-xs text-slate-600"
            />
          </div>

          <div className="rounded-md border border-dashed border-slate-300 p-3">
            <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-700">
              <UploadCloud className="h-4 w-4 text-emerald-600" />
              Planta Arquitetônica Base (.DXF — opcional)
            </label>
            <input
              type="file"
              accept=".dxf"
              onChange={(e) => setDxfFile(e.target.files?.[0] ?? null)}
              className="mt-2 block w-full text-xs text-slate-600"
            />
          </div>
        </div>

        {errorMsg && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {errorMsg}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-slate-300"
        >
          <Zap className="h-4 w-4" />
          {submitting
            ? "Enviando e enfileirando inferência..."
            : "Criar Projeto e Iniciar Visão Computacional"}
        </button>
      </form>

      {jobId && (
        <JobProgressSSE
          jobId={jobId}
          title="Inferência YOLO + OCR + Cores (vision_queue)"
          onCompleted={() => router.push("/editor")}
        />
      )}
    </div>
  );
}
