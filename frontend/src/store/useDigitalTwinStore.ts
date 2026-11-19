"use client";

import { temporal } from "zundo";
import { create } from "zustand";
import type {
  BoundingBox,
  CircuitSpec,
  ComplianceReport,
  DigitalTwinJSON,
  InspectionStatus,
  PanelComponent,
  SpatialCalibration,
} from "@/types/digitalTwin";

export const DEMO_DIGITAL_TWIN: DigitalTwinJSON = {
  schema_version: "1.0.0",
  project_id: "00000000-0000-0000-0000-000000000001",
  inspection_id: "00000000-0000-0000-0000-000000000101",
  panel: {
    panel_id: "QDC-01",
    name: "Quadro de Distribuição Principal",
    location: "Hall de Serviço — Térreo",
    supply_system: "BIFASICO_127_220V",
    grounding_scheme: "TN_S",
    nominal_voltage_v: 220,
    main_breaker_id: "DJ-GERAL",
    has_idr: true,
    has_dps: false,
    has_pe_busbar: true,
    has_neutral_busbar: true,
    pe_neutral_separated: true,
    door_grounding_present: true,
    warning_sign_nr10_present: false,
    unifilar_diagram_inside_present: false,
  },
  components: [
    {
      component_id: "DJ-GERAL",
      label: "Q1 (DJ Geral)",
      component_type: "DISJUNTOR_GERAL",
      poles: 2,
      rated_current_a: 50,
      trip_curve: "C",
      breaking_capacity_ka: 6,
      bbox: { x: 0.08, y: 0.14, w: 0.18, h: 0.34 },
      detection_confidence: 0.96,
      ocr_reading: {
        raw_text: "WEG C50 6kA",
        confidence: 0.93,
        requires_human_review: false,
      },
      requires_human_review: false,
      verified_by_human: true,
    },
    {
      component_id: "IDR-01",
      label: "IDR 63A 30mA",
      component_type: "IDR",
      poles: 2,
      rated_current_a: 63,
      sensitivity_ma: 30,
      bbox: { x: 0.30, y: 0.14, w: 0.18, h: 0.34 },
      detection_confidence: 0.74,
      ocr_reading: {
        raw_text: "63A 30mA",
        confidence: 0.71,
        requires_human_review: true,
      },
      requires_human_review: true,
      verified_by_human: false,
      parent_component_id: "DJ-GERAL",
    },
    {
      component_id: "DJ-C1",
      label: "C1 Iluminação",
      component_type: "DISJUNTOR_CIRCUITO",
      poles: 1,
      rated_current_a: 10,
      trip_curve: "B",
      bbox: { x: 0.54, y: 0.16, w: 0.11, h: 0.32 },
      detection_confidence: 0.92,
      requires_human_review: false,
      verified_by_human: true,
      parent_component_id: "IDR-01",
    },
    {
      component_id: "DJ-C2",
      label: "C2 Tomadas",
      component_type: "DISJUNTOR_CIRCUITO",
      poles: 1,
      rated_current_a: 20,
      trip_curve: "C",
      bbox: { x: 0.68, y: 0.16, w: 0.11, h: 0.32 },
      detection_confidence: 0.89,
      requires_human_review: false,
      verified_by_human: true,
      parent_component_id: "IDR-01",
    },
    {
      component_id: "CAB-N1",
      label: "Neutro Principal",
      component_type: "CABO_NEUTRO",
      bbox: { x: 0.14, y: 0.62, w: 0.24, h: 0.16 },
      detection_confidence: 0.88,
      cable_spec: {
        conductor_role: "NEUTRO",
        section_mm2: 10,
        insulation_type: "PVC_70C",
        color: "AZUL_CLARO",
        color_confidence: 0.91,
        requires_human_review: false,
      },
      requires_human_review: false,
      verified_by_human: true,
    },
  ],
  circuits: [
    {
      circuit_id: "C1",
      name: "Iluminação Sala e Corredor",
      circuit_kind: "ILUMINACAO",
      phase_allocation: "F1",
      voltage_v: 127,
      load_power_va: 900,
      power_factor: 0.92,
      length_m: 18,
      installation_method: "B1",
      ambient_temp_c: 30,
      grouping_count: 2,
      is_wet_area: false,
      is_external_area: false,
      breaker_component_id: "DJ-C1",
      idr_component_id: "IDR-01",
      cable_phase_mm2: 1.5,
      cable_neutral_mm2: 1.5,
      cable_pe_mm2: 1.5,
      cable_phase_color: "PRETO",
      cable_neutral_color: "AZUL_CLARO",
      cable_pe_color: "VERDE",
      plan_x_m: 3.5,
      plan_y_m: 2.8,
    },
    {
      circuit_id: "C2",
      name: "Tomadas Banheiro / Área Molhada",
      circuit_kind: "TOMADAS_USO_GERAL",
      phase_allocation: "F2",
      voltage_v: 127,
      load_power_va: 1800,
      power_factor: 0.92,
      length_m: 14,
      installation_method: "B1",
      ambient_temp_c: 30,
      grouping_count: 2,
      is_wet_area: true,
      is_external_area: false,
      breaker_component_id: "DJ-C2",
      idr_component_id: "IDR-01",
      cable_phase_mm2: 2.5,
      cable_neutral_mm2: 2.5,
      cable_pe_mm2: 2.5,
      cable_phase_color: "VERMELHO",
      cable_neutral_color: "AZUL_CLARO",
      cable_pe_color: "VERDE",
      plan_x_m: 6.2,
      plan_y_m: 4.1,
    },
  ],
  spatial_calibration: {
    base_dxf_path: "/app/storage/uploads/base_dxf/demo_planta.dxf",
    origin_x: 1.2,
    origin_y: 1.5,
    scale_px_per_meter: 60,
    calibrated_by_human: false,
  },
};

interface DigitalTwinState {
  status: InspectionStatus;
  digitalTwin: DigitalTwinJSON;
  selectedComponentId: string | null;
  selectedCircuitId: string | null;
  complianceReport: ComplianceReport | null;
  signedSha256: string | null;
  validatedByName: string | null;
  validatedByCrea: string | null;
  artNumber: string | null;

  setDigitalTwin: (twin: DigitalTwinJSON, status?: InspectionStatus) => void;
  selectComponent: (componentId: string | null) => void;
  selectCircuit: (circuitId: string | null) => void;
  updateComponentBBox: (componentId: string, bbox: BoundingBox) => void;
  verifyComponent: (componentId: string, verified: boolean) => void;
  updateComponentSpecs: (componentId: string, patch: Partial<PanelComponent>) => void;
  updateCircuit: (circuitId: string, patch: Partial<CircuitSpec>) => void;
  updateSpatialCalibration: (patch: Partial<SpatialCalibration>) => void;
  setComplianceReport: (report: ComplianceReport | null) => void;
  markSignedOff: (payload: {
    sha256: string;
    engineerName: string;
    engineerCrea: string;
    artNumber?: string | null;
  }) => void;
  markExported: () => void;
}

export const useDigitalTwinStore = create<DigitalTwinState>()(
  temporal(
    (set) => ({
      status: "AI_PROCESSED",
      digitalTwin: DEMO_DIGITAL_TWIN,
      selectedComponentId: "IDR-01",
      selectedCircuitId: "C1",
      complianceReport: null,
      signedSha256: null,
      validatedByName: null,
      validatedByCrea: null,
      artNumber: null,

      setDigitalTwin: (twin, status) =>
        set((state) => ({
          digitalTwin: twin,
          status: status ?? state.status,
        })),

      selectComponent: (componentId) => set({ selectedComponentId: componentId }),
      selectCircuit: (circuitId) => set({ selectedCircuitId: circuitId }),

      updateComponentBBox: (componentId, bbox) =>
        set((state) => ({
          digitalTwin: {
            ...state.digitalTwin,
            components: state.digitalTwin.components.map((c) =>
              c.component_id === componentId ? { ...c, bbox } : c
            ),
          },
          // Any engineering edit invalidates prior sign-off
          status:
            state.status === "ENGINEER_VALIDATED" || state.status === "EXPORTED"
              ? "AI_PROCESSED"
              : state.status,
          signedSha256: null,
        })),

      verifyComponent: (componentId, verified) =>
        set((state) => ({
          digitalTwin: {
            ...state.digitalTwin,
            components: state.digitalTwin.components.map((c) =>
              c.component_id === componentId ? { ...c, verified_by_human: verified } : c
            ),
          },
        })),

      updateComponentSpecs: (componentId, patch) =>
        set((state) => ({
          digitalTwin: {
            ...state.digitalTwin,
            components: state.digitalTwin.components.map((c) =>
              c.component_id === componentId ? { ...c, ...patch } : c
            ),
          },
          status:
            state.status === "ENGINEER_VALIDATED" || state.status === "EXPORTED"
              ? "AI_PROCESSED"
              : state.status,
          signedSha256: null,
        })),

      updateCircuit: (circuitId, patch) =>
        set((state) => ({
          digitalTwin: {
            ...state.digitalTwin,
            circuits: state.digitalTwin.circuits.map((circ) =>
              circ.circuit_id === circuitId ? { ...circ, ...patch } : circ
            ),
          },
          status:
            state.status === "ENGINEER_VALIDATED" || state.status === "EXPORTED"
              ? "AI_PROCESSED"
              : state.status,
          signedSha256: null,
        })),

      updateSpatialCalibration: (patch) =>
        set((state) => ({
          digitalTwin: {
            ...state.digitalTwin,
            spatial_calibration: state.digitalTwin.spatial_calibration
              ? { ...state.digitalTwin.spatial_calibration, ...patch }
              : {
                  base_dxf_path: "",
                  origin_x: 0,
                  origin_y: 0,
                  scale_px_per_meter: 50,
                  calibrated_by_human: false,
                  ...patch,
                },
          },
        })),

      setComplianceReport: (report) => set({ complianceReport: report }),

      markSignedOff: ({ sha256, engineerName, engineerCrea, artNumber }) =>
        set({
          status: "ENGINEER_VALIDATED",
          signedSha256: sha256,
          validatedByName: engineerName,
          validatedByCrea: engineerCrea,
          artNumber: artNumber ?? null,
        }),

      markExported: () => set({ status: "EXPORTED" }),
    }),
    {
      limit: 50,
      partialize: (state) => ({
        digitalTwin: state.digitalTwin,
      }),
    }
  )
);
