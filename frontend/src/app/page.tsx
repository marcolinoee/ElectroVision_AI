"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Cpu, FolderPlus, PenTool, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { ProjectSummary } from "@/types/digitalTwin";

export default function DashboardPage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [offlineNotice, setOfflineNotice] = useState(false);

  useEffect(() => {
    api
      .listProjects()
      .then((data) => {
        setProjects(data);
        setOfflineNotice(false);
      })
      .catch(() => {
        setOfflineNotice(true);
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Painel de Engenharia Elétrica</h1>
          <p className="text-sm text-slate-600">
            Sistema 100% local-first de diagnóstico por visão computacional, conformidade NBR 5410 /
            NR-10 e geração CAD auditada.
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/projects/new"
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
          >
            <FolderPlus className="h-4 w-4" />
            Novo Projeto
          </Link>
          <Link
            href="/editor"
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50"
          >
            <PenTool className="h-4 w-4" />
            Abrir Editor Digital Twin
          </Link>
        </div>
      </div>

      {/* Quick Architecture Cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
            <ShieldCheck className="h-4 w-4 text-emerald-600" />
            Sign-Off CREA / ART &amp; SHA-256
          </div>
          <p className="mt-1 text-xs text-slate-600">
            Exportações oficiais (.DXF, .DOCX, .XLSX) só são liberadas após revisão humana dos itens
            com confiança &lt; 0.80 e assinatura criptográfica.
          </p>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
            <PenTool className="h-4 w-4 text-blue-600" />
            CAD Auditado (ezdxf.audit)
          </div>
          <p className="mt-1 text-xs text-slate-600">
            Diagrama Unifilar automático (.DXF/.SVG) e Planta Baixa condicionada exclusivamente a
            arquivo .DXF arquitetônico base calibrado.
          </p>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
            <Cpu className="h-4 w-4 text-indigo-600" />
            Active Learning Blindado
          </div>
          <p className="mt-1 text-xs text-slate-600">
            Promoção atômica de pesos YOLO (.pt) condicionada a ganho de mAP50-95 no Golden Holdout
            Set e Recall ≥ 95% em IDR, DPS e Disjuntor.
          </p>
        </div>
      </div>

      {/* Projects List */}
      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="text-sm font-bold text-slate-900">Projetos Recentes</h2>
          {offlineNotice && (
            <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
              API local indisponível — modo demonstração disponível no Editor
            </span>
          )}
        </div>

        {loading ? (
          <div className="p-6 text-sm text-slate-500">Carregando projetos...</div>
        ) : projects.length === 0 ? (
          <div className="p-6 text-sm text-slate-600">
            Nenhum projeto cadastrado ainda. Crie seu primeiro projeto ou explore o{" "}
            <Link href="/editor" className="font-semibold text-blue-600 hover:underline">
              Editor Digital Twin interativo
            </Link>
            .
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {projects.map((p) => (
              <div
                key={p.id}
                className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 hover:bg-slate-50"
              >
                <div>
                  <div className="text-sm font-semibold text-slate-900">{p.name}</div>
                  <div className="text-xs text-slate-500">
                    Cliente: {p.client_name} • {p.supply_system} • {p.grounding_scheme} (
                    {p.nominal_voltage_v}V)
                  </div>
                </div>
                <Link
                  href="/editor"
                  className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-800"
                >
                  Abrir Editor <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
