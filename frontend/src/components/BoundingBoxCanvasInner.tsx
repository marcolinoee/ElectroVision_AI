"use client";

import { useEffect, useRef } from "react";
import { Layer, Rect, Stage, Text, Transformer } from "react-konva";
import type Konva from "konva";
import { CheckCircle2, AlertTriangle } from "lucide-react";
import { useDigitalTwinStore } from "@/store/useDigitalTwinStore";

const STAGE_W = 760;
const STAGE_H = 440;

export default function BoundingBoxCanvasInner() {
  const {
    digitalTwin,
    selectedComponentId,
    selectComponent,
    updateComponentBBox,
    verifyComponent,
  } = useDigitalTwinStore();

  const trRef = useRef<Konva.Transformer | null>(null);
  const shapeRefs = useRef<Record<string, Konva.Rect | null>>({});

  useEffect(() => {
    const tr = trRef.current;
    if (!tr) return;
    if (selectedComponentId && shapeRefs.current[selectedComponentId]) {
      tr.nodes([shapeRefs.current[selectedComponentId]!]);
    } else {
      tr.nodes([]);
    }
    tr.getLayer()?.batchDraw();
  }, [selectedComponentId, digitalTwin.components]);

  const selectedComp = digitalTwin.components.find(
    (c) => c.component_id === selectedComponentId
  );

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      {/* Interactive Konva Stage */}
      <div className="lg:col-span-2 overflow-hidden rounded-lg border border-slate-200 bg-slate-900 p-2">
        <div className="mb-2 flex items-center justify-between px-2 text-xs text-slate-300">
          <span>Editor de Bounding Boxes (arraste e redimensione os componentes detectados)</span>
          <span className="font-mono text-slate-400">
            {digitalTwin.components.length} componentes
          </span>
        </div>
        <div className="overflow-x-auto">
          <Stage
            width={STAGE_W}
            height={STAGE_H}
            onMouseDown={(e) => {
              if (e.target === e.target.getStage()) {
                selectComponent(null);
              }
            }}
            className="mx-auto rounded bg-slate-800"
          >
            <Layer>
              {/* Simulated Panel DIN-Rail Backdrop */}
              <Rect x={24} y={24} width={STAGE_W - 48} height={STAGE_H - 48} fill="#1e293b" stroke="#475569" strokeWidth={2} cornerRadius={6} />
              <Rect x={48} y={130} width={STAGE_W - 96} height={16} fill="#64748b" />
              <Rect x={48} y={310} width={STAGE_W - 96} height={12} fill="#334155" />

              {digitalTwin.components.map((comp) => {
                if (!comp.bbox) return null;
                const px = comp.bbox.x * STAGE_W;
                const py = comp.bbox.y * STAGE_H;
                const pw = comp.bbox.w * STAGE_W;
                const ph = comp.bbox.h * STAGE_H;

                const needsReview = comp.requires_human_review && !comp.verified_by_human;
                const strokeColor = needsReview
                  ? "#f59e0b"
                  : comp.verified_by_human
                  ? "#10b981"
                  : "#3b82f6";

                return (
                  <Rect
                    key={comp.component_id}
                    ref={(node) => {
                      shapeRefs.current[comp.component_id] = node;
                    }}
                    x={px}
                    y={py}
                    width={pw}
                    height={ph}
                    fill={`${strokeColor}26`}
                    stroke={strokeColor}
                    strokeWidth={selectedComponentId === comp.component_id ? 3 : 2}
                    draggable
                    onClick={() => selectComponent(comp.component_id)}
                    onTap={() => selectComponent(comp.component_id)}
                    onDragEnd={(e) => {
                      const nx = Math.max(0, Math.min(1 - comp.bbox!.w, e.target.x() / STAGE_W));
                      const ny = Math.max(0, Math.min(1 - comp.bbox!.h, e.target.y() / STAGE_H));
                      updateComponentBBox(comp.component_id, {
                        x: Number(nx.toFixed(4)),
                        y: Number(ny.toFixed(4)),
                        w: comp.bbox!.w,
                        h: comp.bbox!.h,
                      });
                    }}
                    onTransformEnd={() => {
                      const node = shapeRefs.current[comp.component_id];
                      if (!node) return;
                      const scaleX = node.scaleX();
                      const scaleY = node.scaleY();
                      node.scaleX(1);
                      node.scaleY(1);

                      const newW = Math.max(20, node.width() * scaleX);
                      const newH = Math.max(20, node.height() * scaleY);
                      const nx = Math.max(0, Math.min(1, node.x() / STAGE_W));
                      const ny = Math.max(0, Math.min(1, node.y() / STAGE_H));
                      const nw = Math.max(0.02, Math.min(1 - nx, newW / STAGE_W));
                      const nh = Math.max(0.02, Math.min(1 - ny, newH / STAGE_H));
                      updateComponentBBox(comp.component_id, {
                        x: Number(nx.toFixed(4)),
                        y: Number(ny.toFixed(4)),
                        w: Number(nw.toFixed(4)),
                        h: Number(nh.toFixed(4)),
                      });
                    }}
                  />
                );
              })}

              {digitalTwin.components.map((comp) => {
                if (!comp.bbox) return null;
                const px = comp.bbox.x * STAGE_W;
                const py = comp.bbox.y * STAGE_H;
                const needsReview = comp.requires_human_review && !comp.verified_by_human;
                return (
                  <Text
                    key={`${comp.component_id}-label`}
                    x={px + 4}
                    y={Math.max(4, py - 18)}
                    text={`${comp.label} (${Math.round(comp.detection_confidence * 100)}%)`}
                    fontSize={12}
                    fontStyle="bold"
                    fill={needsReview ? "#fbbf24" : "#f8fafc"}
                    listening={false}
                  />
                );
              })}

              <Transformer
                ref={trRef}
                rotateEnabled={false}
                boundBoxFunc={(oldBox, newBox) => {
                  if (newBox.width < 20 || newBox.height < 20) return oldBox;
                  return newBox;
                }}
              />
            </Layer>
          </Stage>
        </div>
      </div>

      {/* Inspector Sidebar */}
      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="text-sm font-bold text-slate-900">Inspetor de Componente</h3>
        {selectedComp ? (
          <div className="mt-3 space-y-3 text-xs">
            <div>
              <div className="text-slate-500">ID / Rótulo</div>
              <div className="font-mono font-semibold text-slate-900">
                {selectedComp.component_id} — {selectedComp.label}
              </div>
            </div>
            <div>
              <div className="text-slate-500">Tipo</div>
              <div className="font-semibold text-slate-800">{selectedComp.component_type}</div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded bg-slate-50 p-2">
                <div className="text-slate-500">Confiança YOLO</div>
                <div
                  className={`font-mono text-sm font-bold ${
                    selectedComp.detection_confidence < 0.8 ? "text-amber-600" : "text-emerald-700"
                  }`}
                >
                  {(selectedComp.detection_confidence * 100).toFixed(1)}%
                </div>
              </div>
              <div className="rounded bg-slate-50 p-2">
                <div className="text-slate-500">OCR</div>
                <div className="font-mono text-xs font-semibold text-slate-800">
                  {selectedComp.ocr_reading
                    ? `${selectedComp.ocr_reading.raw_text} (${Math.round(
                        selectedComp.ocr_reading.confidence * 100
                      )}%)`
                    : "N/A"}
                </div>
              </div>
            </div>

            {selectedComp.requires_human_review && !selectedComp.verified_by_human ? (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-2.5 text-amber-900">
                <div className="flex items-center gap-1.5 font-semibold">
                  <AlertTriangle className="h-4 w-4 text-amber-600" />
                  Revisão Humana Obrigatória (&lt; 0.80)
                </div>
                <p className="mt-1">
                  Confirme a caixa delimitadora e os dados nominais antes do Sign-Off CREA.
                </p>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 rounded-md bg-emerald-50 p-2 text-emerald-800">
                <CheckCircle2 className="h-4 w-4" />
                Componente verificado.
              </div>
            )}

            <button
              type="button"
              onClick={() =>
                verifyComponent(selectedComp.component_id, !selectedComp.verified_by_human)
              }
              className={`w-full rounded-md px-3 py-2 text-xs font-semibold text-white transition ${
                selectedComp.verified_by_human
                  ? "bg-slate-600 hover:bg-slate-700"
                  : "bg-emerald-600 hover:bg-emerald-700"
              }`}
            >
              {selectedComp.verified_by_human
                ? "Desmarcar Verificação Humana"
                : "Confirmar Verificação Humana"}
            </button>
          </div>
        ) : (
          <p className="mt-3 text-xs text-slate-500">
            Selecione uma caixa delimitadora no canvas para inspecionar e validar.
          </p>
        )}
      </div>
    </div>
  );
}
