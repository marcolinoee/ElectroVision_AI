"use client";

import { Circle, Group, Layer, Line, Rect, Stage, Text } from "react-konva";
import { CheckCircle2 } from "lucide-react";
import { useDigitalTwinStore } from "@/store/useDigitalTwinStore";

const STAGE_W = 760;
const STAGE_H = 400;
const PX_PER_M = 60;

export default function CanvasPlantaInner() {
  const { digitalTwin, updateSpatialCalibration, updateCircuit } =
    useDigitalTwinStore();

  const cal = digitalTwin.spatial_calibration;
  const originX = (cal?.origin_x ?? 1.2) * PX_PER_M;
  const originY = (cal?.origin_y ?? 1.5) * PX_PER_M;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <h3 className="text-sm font-bold text-slate-900">
            Calibração Espacial sobre Planta Baixa (.DXF Arquitetônico Base)
          </h3>
          <p className="text-xs text-slate-600">
            Arraste o Quadro (vermelho) e os Pontos de Circuitos (azul) sobre o DXF base. A
            exportação de Planta Elétrica (.DXF) só é liberada após confirmação manual.
          </p>
        </div>

        <button
          type="button"
          onClick={() =>
            updateSpatialCalibration({
              calibrated_by_human: !(cal?.calibrated_by_human ?? false),
            })
          }
          className={`inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs font-semibold text-white ${
            cal?.calibrated_by_human
              ? "bg-emerald-600 hover:bg-emerald-700"
              : "bg-blue-600 hover:bg-blue-700"
          }`}
        >
          <CheckCircle2 className="h-4 w-4" />
          {cal?.calibrated_by_human
            ? "Calibração Confirmada (Clique para Editar)"
            : "Confirmar Calibração Espacial"}
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-slate-900 p-3">
        <Stage width={STAGE_W} height={STAGE_H} className="mx-auto rounded bg-slate-950">
          <Layer>
            {/* Architectural Base Reference Grid */}
            <Rect
              x={30}
              y={30}
              width={STAGE_W - 60}
              height={STAGE_H - 60}
              stroke="#475569"
              strokeWidth={2}
            />
            <Line points={[30, 200, STAGE_W - 30, 200]} stroke="#334155" dash={[6, 6]} />
            <Line points={[380, 30, 380, STAGE_H - 30]} stroke="#334155" dash={[6, 6]} />

            {/* Conduits from Panel to Circuits */}
            {digitalTwin.circuits.map((circ) => {
              const px = (circ.plan_x_m ?? 4.0) * PX_PER_M;
              const py = (circ.plan_y_m ?? 3.0) * PX_PER_M;
              return (
                <Line
                  key={`conduit-${circ.circuit_id}`}
                  points={[originX, originY, px, py]}
                  stroke="#22c55e"
                  strokeWidth={2}
                  dash={[4, 4]}
                />
              );
            })}

            {/* Draggable Panel Origin */}
            <Group
              x={originX}
              y={originY}
              draggable
              onDragEnd={(e) => {
                updateSpatialCalibration({
                  origin_x: Number((e.target.x() / PX_PER_M).toFixed(2)),
                  origin_y: Number((e.target.y() / PX_PER_M).toFixed(2)),
                });
              }}
            >
              <Rect x={-16} y={-10} width={32} height={20} fill="#ef4444" stroke="#ffffff" strokeWidth={2} />
              <Text x={-20} y={14} text={digitalTwin.panel.panel_id} fontSize={11} fontStyle="bold" fill="#fca5a5" />
            </Group>

            {/* Draggable Circuit Points */}
            {digitalTwin.circuits.map((circ) => {
              const px = (circ.plan_x_m ?? 4.0) * PX_PER_M;
              const py = (circ.plan_y_m ?? 3.0) * PX_PER_M;
              return (
                <Group
                  key={circ.circuit_id}
                  x={px}
                  y={py}
                  draggable
                  onDragEnd={(e) => {
                    updateCircuit(circ.circuit_id, {
                      plan_x_m: Number((e.target.x() / PX_PER_M).toFixed(2)),
                      plan_y_m: Number((e.target.y() / PX_PER_M).toFixed(2)),
                    });
                  }}
                >
                  <Circle radius={10} fill="#3b82f6" stroke="#ffffff" strokeWidth={2} />
                  <Text x={14} y={-6} text={circ.circuit_id} fontSize={11} fontStyle="bold" fill="#93c5fd" />
                </Group>
              );
            })}
          </Layer>
        </Stage>
      </div>
    </div>
  );
}
