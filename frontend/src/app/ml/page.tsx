"use client";

import { useEffect, useState } from "react";
import { BookOpen, Cpu, Play, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { JobProgressSSE } from "@/components/JobProgressSSE";
import type { ModelVersionSummary } from "@/types/digitalTwin";

export default function MLTrainingPage() {
  const [models, setModels] = useState<ModelVersionSummary[]>([]);
  const [epochs, setEpochs] = useState(20);
  const [replayRatio, setReplayRatio] = useState(0.5);
  const [trainJobId, setTrainJobId] = useState<string | null>(null);
  const [harvestJobId, setHarvestJobId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [standardCode, setStandardCode] = useState("NBR 5410");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [pdfNotice, setPdfNotice] = useState<string | null>(null);

  useEffect(() => {
    api
      .listModels()
      .then(setModels)
      .catch(() => {
        // Offline / empty DB fallback
      });
  }, []);

  async function handleStartTraining() {
    setErrorMsg(null);
    try {
      const dispatch = await api.dispatchTraining(epochs, replayRatio);
      setTrainJobId(dispatch.job_id);
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : "Falha ao despachar treinamento Active Learning."
      );
    }
  }

  async function handleStartHarvest(maxMb: number, maxItems: number) {
    setErrorMsg(null);
    try {
      const dispatch = await api.startHarvest(maxMb, undefined, maxItems);
      setHarvestJobId(dispatch.job_id);
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : "Falha ao iniciar Dataset Harvester."
      );
    }
  }

  async function handleImportPdf(e: React.FormEvent) {
    e.preventDefault();
    if (!pdfFile) return;
    setPdfNotice(null);
    try {
      const res = await api.importNormPdf(standardCode, pdfFile);
      setPdfNotice(`PDF '${res.filename}' armazenado localmente (SHA-256: ${res.sha256.slice(0, 12)}...).`);
    } catch (err) {
      setPdfNotice(err instanceof Error ? err.message : "Erro ao importar PDF.");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900">
          MLOps — Active Learning Blindado &amp; Base Normativa Local
        </h1>
        <p className="text-sm text-slate-600">
          Um novo peso <code>.pt</code> só é promovido atomicamente se melhorar o{" "}
          <strong>mAP50-95</strong> no <em>Golden Holdout Set</em> fixo e mantiver{" "}
          <strong>Recall ≥ 95%</strong> em IDR, DPS e Disjuntor.
        </p>
      </div>

      {/* Public Dataset Harvester (1 GB Hard Quota) */}
      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
          <Cpu className="h-4 w-4 text-emerald-600" />
          Dataset Harvester — Coleta Pública de Engenharia Elétrica (Teto Rígido 1 GB)
        </div>
        <p className="mt-1 text-xs text-slate-600">
          Coleta imagens abertas (Wikimedia Commons, Hugging Face Streaming, YOLO públicos e símbolos
          CAD IEC/NBR) com filtro de blur, deduplicação pHash e teto de 950 MB úteis.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => handleStartHarvest(20, 25)}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50"
          >
            <Play className="h-3.5 w-3.5" />
            Executar Dry-Run (20 MB)
          </button>
          <button
            type="button"
            onClick={() => handleStartHarvest(950, 1500)}
            className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-700"
          >
            <Play className="h-3.5 w-3.5" />
            Iniciar Coleta Completa (950 MB)
          </button>
        </div>
        {harvestJobId && (
          <div className="mt-4">
            <JobProgressSSE
              jobId={harvestJobId}
              title="Dataset Harvester (train_queue)"
            />
          </div>
        )}
      </div>

      {/* Trigger Active Learning */}
      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
          <Cpu className="h-4 w-4 text-blue-600" />
          Executar Ciclo de Fine-Tuning YOLO (train_queue)
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700">Épocas</label>
            <input
              type="number"
              min={1}
              max={200}
              value={epochs}
              onChange={(e) => setEpochs(Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700">
              Replay Buffer Ratio (anti-catastrophic forgetting)
            </label>
            <input
              type="number"
              step={0.1}
              min={0}
              max={2}
              value={replayRatio}
              onChange={(e) => setReplayRatio(Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="flex items-end">
            <button
              type="button"
              onClick={handleStartTraining}
              className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
            >
              <Play className="h-4 w-4" />
              Iniciar Treinamento
            </button>
          </div>
        </div>

        {errorMsg && (
          <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {errorMsg}
          </div>
        )}

        {trainJobId && (
          <div className="mt-4">
            <JobProgressSSE
              jobId={trainJobId}
              title="Treinamento Active Learning + Golden Holdout Eval"
              onCompleted={() => api.listModels().then(setModels).catch(() => {})}
            />
          </div>
        )}
      </div>

      {/* Model Versions Table */}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50 px-4 py-2.5 text-sm font-semibold text-slate-800">
          <ShieldCheck className="h-4 w-4 text-emerald-600" />
          Registro Atômico de Modelos (.pt)
        </div>
        {models.length === 0 ? (
          <div className="p-4 text-xs text-slate-500">
            Nenhuma versão registrada ainda no banco de dados local.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-xs">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-3 py-2 text-left">Versão</th>
                  <th className="px-3 py-2 text-right">mAP50</th>
                  <th className="px-3 py-2 text-right">mAP50-95</th>
                  <th className="px-3 py-2 text-right">Recall IDR</th>
                  <th className="px-3 py-2 text-right">Recall DPS</th>
                  <th className="px-3 py-2 text-right">Recall Disjuntor</th>
                  <th className="px-3 py-2 text-center">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {models.map((m) => (
                  <tr key={m.id}>
                    <td className="px-3 py-2 font-mono font-semibold">{m.version_tag}</td>
                    <td className="px-3 py-2 text-right font-mono">{(m.map50 * 100).toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right font-mono">{(m.map50_95 * 100).toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right font-mono">{(m.critical_recall_idr * 100).toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right font-mono">{(m.critical_recall_dps * 100).toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right font-mono">{(m.critical_recall_disjuntor * 100).toFixed(1)}%</td>
                    <td className="px-3 py-2 text-center">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${
                          m.is_active
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {m.is_active ? "ATIVO" : "ARQUIVADO"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Local Normative PDF Import (ABNT Copyright-Compliant) */}
      <form
        onSubmit={handleImportPdf}
        className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
      >
        <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
          <BookOpen className="h-4 w-4 text-indigo-600" />
          Importar PDF Normativo Próprio para Indexação Local (pgvector)
        </div>
        <p className="mt-1 text-xs text-slate-600">
          Para respeitar direitos autorais da ABNT, importe localmente seus próprios exemplares PDF
          para indexação vetorial (ONNX <code>multilingual-e5-small</code>) apenas como suporte de
          citação.
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <select
            value={standardCode}
            onChange={(e) => setStandardCode(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-xs"
          >
            <option value="NBR 5410">NBR 5410</option>
            <option value="NR-10">NR-10</option>
            <option value="NBR 14039">NBR 14039</option>
          </select>
          <input
            type="file"
            accept=".pdf"
            onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)}
            className="text-xs text-slate-600"
          />
          <button
            type="submit"
            disabled={!pdfFile}
            className="rounded-md bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:bg-slate-300"
          >
            Importar PDF Local
          </button>
        </div>
        {pdfNotice && <p className="mt-2 text-xs font-medium text-indigo-700">{pdfNotice}</p>}
      </form>
    </div>
  );
}
