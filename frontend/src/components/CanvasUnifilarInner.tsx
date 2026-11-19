"use client";

import { Circle, Group, Layer, Line, Rect, Stage, Text } from "react-konva";
import { useDigitalTwinStore } from "@/store/useDigitalTwinStore";

export default function CanvasUnifilarInner() {
  const { digitalTwin, selectedCircuitId, selectCircuit } = useDigitalTwinStore();
  const compMap = new Map(digitalTwin.components.map((c) => [c.component_id, c]));

  const circuits = digitalTwin.circuits;
  const stageW = Math.max(760, 140 + circuits.length * 160);
  const stageH = 420;
  const feederX = stageW / 2;

  const mainBreaker = digitalTwin.panel.main_breaker_id
    ? compMap.get(digitalTwin.panel.main_breaker_id)
    : undefined;

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="mb-2 flex items-center justify-between text-xs text-slate-600">
        <span className="font-semibold text-slate-900">
          Diagrama Unifilar Interativo — {digitalTwin.panel.name} ({digitalTwin.panel.supply_system})
        </span>
        <span className="font-mono">Aterramento: {digitalTwin.panel.grounding_scheme}</span>
      </div>

      <Stage width={stageW} height={stageH} className="mx-auto rounded border border-slate-100 bg-slate-50">
        <Layer>
          {/* Incoming Feeder */}
          <Line points={[feederX, 24, feederX, 60]} stroke="#dc2626" strokeWidth={3} />
          <Rect
            x={feederX - 24}
            y={60}
            width={48}
            height={34}
            fill="#fef2f2"
            stroke="#dc2626"
            strokeWidth={2}
            cornerRadius={4}
          />
          <Text
            x={feederX + 32}
            y={68}
            text={`DJ GERAL: ${mainBreaker?.trip_curve ?? "C"}${mainBreaker?.rated_current_a ?? "?"}A`}
            fontSize={12}
            fontStyle="bold"
            fill="#991b1b"
          />
          <Line points={[feederX, 94, feederX, 136]} stroke="#dc2626" strokeWidth={3} />

          {/* DPS Branch if present */}
          {digitalTwin.panel.has_dps && (
            <Group>
              <Line points={[70, 136, 70, 96]} stroke="#16a34a" strokeWidth={2} />
              <Rect x={52} y={66} width={36} height={30} fill="#f0fdf4" stroke="#16a34a" strokeWidth={2} />
              <Text x={58} y={76} text="DPS" fontSize={11} fontStyle="bold" fill="#166534" />
            </Group>
          )}

          {/* Main Horizontal Busbar */}
          <Line points={[36, 136, stageW - 36, 136]} stroke="#dc2626" strokeWidth={5} />

          {/* Outgoing Circuits */}
          {circuits.map((circ, idx) => {
            const cx = 100 + idx * 160;
            const breaker = circ.breaker_component_id
              ? compMap.get(circ.breaker_component_id)
              : undefined;
            const idr = circ.idr_component_id ? compMap.get(circ.idr_component_id) : undefined;
            const isSelected = selectedCircuitId === circ.circuit_id;

            return (
              <Group
                key={circ.circuit_id}
                onClick={() => selectCircuit(circ.circuit_id)}
                onTap={() => selectCircuit(circ.circuit_id)}
              >
                <Line
                  points={[cx, 136, cx, 178]}
                  stroke={isSelected ? "#1d4ed8" : "#3b82f6"}
                  strokeWidth={isSelected ? 3 : 2}
                />
                <Rect
                  x={cx - 18}
                  y={178}
                  width={36}
                  height={36}
                  fill={isSelected ? "#dbeafe" : "#eff6ff"}
                  stroke={isSelected ? "#1e40af" : "#2563eb"}
                  strokeWidth={isSelected ? 3 : 2}
                  cornerRadius={4}
                />
                <Text
                  x={cx - 14}
                  y={191}
                  text={`${breaker?.trip_curve ?? "C"}${breaker?.rated_current_a ?? "?"}`}
                  fontSize={11}
                  fontStyle="bold"
                  fill="#1e3a8a"
                />
                <Line
                  points={[cx, 214, cx, 290]}
                  stroke={isSelected ? "#1d4ed8" : "#3b82f6"}
                  strokeWidth={2}
                />

                {idr && (
                  <Group>
                    <Circle x={cx} y={248} radius={13} fill="#f0fdf4" stroke="#16a34a" strokeWidth={2} />
                    <Text
                      x={cx + 18}
                      y={242}
                      text={`IDR ${idr.sensitivity_ma ?? 30}mA`}
                      fontSize={10}
                      fontStyle="bold"
                      fill="#15803d"
                    />
                  </Group>
                )}

                <Text
                  x={cx - 60}
                  y={300}
                  width={120}
                  align="center"
                  text={circ.circuit_id}
                  fontSize={13}
                  fontStyle="bold"
                  fill="#0f172a"
                />
                <Text
                  x={cx - 65}
                  y={318}
                  width={130}
                  align="center"
                  text={`${circ.cable_phase_mm2}mm² • ${circ.load_power_va}VA`}
                  fontSize={11}
                  fill="#334155"
                />
                <Text
                  x={cx - 70}
                  y={334}
                  width={140}
                  align="center"
                  text={circ.name.slice(0, 22)}
                  fontSize={10}
                  fill="#64748b"
                />
              </Group>
            );
          })}
        </Layer>
      </Stage>
    </div>
  );
}
