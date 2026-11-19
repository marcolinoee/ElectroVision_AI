"use client";

import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";
import type { ComplianceReport, SeverityLevel } from "@/types/digitalTwin";

const SEVERITY_BADGE: Record<SeverityLevel, string> = {
  CRITICA: "bg-red-100 text-red-800 border-red-200",
  ALTA: "bg-orange-100 text-orange-800 border-orange-200",
  MEDIA: "bg-amber-100 text-amber-800 border-amber-200",
  BAIXA: "bg-blue-100 text-blue-800 border-blue-200",
  INFORMATIVA: "bg-slate-100 text-slate-700 border-slate-200",
};

interface ComplianceTableProps {
  report: ComplianceReport | null;
}

export function ComplianceTable({ report }: ComplianceTableProps) {
  if (!report) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-600">
        Clique em <strong>Avaliar Conformidade (NBR 5410 / NR-10)</strong> para executar o motor
        determinístico sobre o Digital Twin atual.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="text-xs text-slate-500">Status Geral</div>
          <div className="mt-1 flex items-center gap-1.5 text-sm font-bold">
            {report.is_compliant ? (
              <>
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                <span className="text-emerald-700">CONFORME</span>
              </>
            ) : (
              <>
                <ShieldAlert className="h-4 w-4 text-red-600" />
                <span className="text-red-700">PENDÊNCIAS</span>
              </>
            )}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="text-xs text-slate-500">Score</div>
          <div className="mt-1 text-lg font-bold text-slate-900">
            {report.compliance_score_pct.toFixed(0)}%
          </div>
        </div>
        <div className="rounded-lg border border-red-200 bg-red-50/50 p-3">
          <div className="text-xs text-red-700">Críticas</div>
          <div className="mt-1 text-lg font-bold text-red-800">{report.critical_count}</div>
        </div>
        <div className="rounded-lg border border-orange-200 bg-orange-50/50 p-3">
          <div className="text-xs text-orange-700">Altas</div>
          <div className="mt-1 text-lg font-bold text-orange-800">{report.high_count}</div>
        </div>
        <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-3">
          <div className="text-xs text-amber-700">Médias / Baixas</div>
          <div className="mt-1 text-lg font-bold text-amber-800">
            {report.medium_count + report.low_count}
          </div>
        </div>
      </div>

      {/* Circuit Calculations */}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-200 bg-slate-50 px-4 py-2.5 text-sm font-semibold text-slate-800">
          Quadro de Cargas Determinístico (Ib ≤ In ≤ Iz &amp; ΔV ≤ 4%)
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-xs">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="px-3 py-2 text-left">Circuito</th>
                <th className="px-3 py-2 text-left">Descrição</th>
                <th className="px-3 py-2 text-right">Ib (A)</th>
                <th className="px-3 py-2 text-right">In (A)</th>
                <th className="px-3 py-2 text-right">Iz (A)</th>
                <th className="px-3 py-2 text-right">ΔV (%)</th>
                <th className="px-3 py-2 text-center">Coord.</th>
                <th className="px-3 py-2 text-center">ΔV OK</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {report.circuit_calculations.map((calc) => (
                <tr key={calc.circuit_id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono font-semibold">{calc.circuit_id}</td>
                  <td className="px-3 py-2 text-slate-700">{calc.circuit_name}</td>
                  <td className="px-3 py-2 text-right font-mono">{calc.design_current_ib_a.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right font-mono">
                    {calc.breaker_rated_in_a ?? "N/I"}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">{calc.corrected_ampacity_iz_a.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right font-mono">{calc.voltage_drop_pct.toFixed(2)}%</td>
                  <td className="px-3 py-2 text-center">
                    <span
                      className={
                        calc.coordination_ok
                          ? "font-semibold text-emerald-700"
                          : "font-semibold text-red-700"
                      }
                    >
                      {calc.coordination_ok ? "OK" : "FALHA"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span
                      className={
                        calc.voltage_drop_ok
                          ? "font-semibold text-emerald-700"
                          : "font-semibold text-amber-700"
                      }
                    >
                      {calc.voltage_drop_ok ? "OK" : "> 4%"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Findings */}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-200 bg-slate-50 px-4 py-2.5 text-sm font-semibold text-slate-800">
          Não-Conformidades Detectadas ({report.findings.length})
        </div>
        {report.findings.length === 0 ? (
          <div className="p-4 text-sm text-emerald-700">
            Nenhuma não-conformidade identificada pelo motor determinístico.
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {report.findings.map((finding, idx) => (
              <div key={`${finding.rule_code}-${finding.target_id}-${idx}`} className="p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded border px-2 py-0.5 text-[11px] font-bold ${
                      SEVERITY_BADGE[finding.severity]
                    }`}
                  >
                    {finding.severity}
                  </span>
                  <span className="font-mono text-xs text-slate-500">
                    {finding.standard_code} • {finding.section_ref} • Alvo: {finding.target_id}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-1.5 text-sm font-semibold text-slate-900">
                  <AlertTriangle className="h-4 w-4 text-amber-600" />
                  {finding.title}
                </div>
                <p className="mt-1 text-xs text-slate-600">{finding.description}</p>
                <p className="mt-1 text-xs font-medium text-blue-700">
                  Ação Recomendada: {finding.recommended_action}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
