export type InspectionStatus =
  | "DRAFT"
  | "AI_PROCESSED"
  | "ENGINEER_VALIDATED"
  | "EXPORTED";

export type ComponentType =
  | "DISJUNTOR_GERAL"
  | "DISJUNTOR_CIRCUITO"
  | "IDR"
  | "DPS"
  | "BARRAMENTO_FASE"
  | "BARRAMENTO_NEUTRO"
  | "BARRAMENTO_TERRA"
  | "CABO_FASE"
  | "CABO_NEUTRO"
  | "CABO_TERRA"
  | "CONTATOR"
  | "RELE_TERMICO"
  | "MEDIDOR"
  | "QUADRO_DISTRIBUICAO"
  | "OUTRO";

export type CableColor =
  | "AZUL_CLARO"
  | "VERDE"
  | "VERDE_AMARELO"
  | "PRETO"
  | "VERMELHO"
  | "BRANCO"
  | "CINZA"
  | "MARROM"
  | "AMARELO"
  | "DESCONHECIDA";

export type SeverityLevel = "CRITICA" | "ALTA" | "MEDIA" | "BAIXA" | "INFORMATIVA";

export type ArtifactType =
  | "UNIFILAR_DXF"
  | "UNIFILAR_SVG"
  | "PLANTA_DXF"
  | "MEMORIAL_DOCX"
  | "RETROFIT_XLSX";

export interface BoundingBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface OCRReading {
  raw_text: string;
  normalized_text?: string | null;
  confidence: number;
  requires_human_review: boolean;
}

export interface CableSpec {
  conductor_role: "FASE" | "NEUTRO" | "TERRA_PE" | "PEN" | "RETORNO";
  section_mm2?: number | null;
  insulation_type: "PVC_70C" | "EPR_90C" | "XLPE_90C";
  color: CableColor;
  color_confidence: number;
  requires_human_review: boolean;
}

export interface PanelComponent {
  component_id: string;
  label: string;
  component_type: ComponentType;
  manufacturer?: string | null;
  model_name?: string | null;
  poles?: number | null;
  rated_current_a?: number | null;
  trip_curve?: "B" | "C" | "D" | null;
  breaking_capacity_ka?: number | null;
  sensitivity_ma?: number | null;
  dps_class?: "I" | "II" | "III" | "I+II" | null;
  dps_uc_v?: number | null;
  dps_imax_ka?: number | null;
  cable_spec?: CableSpec | null;
  bbox?: BoundingBox | null;
  detection_confidence: number;
  ocr_reading?: OCRReading | null;
  requires_human_review: boolean;
  verified_by_human: boolean;
  parent_component_id?: string | null;
}

export interface CircuitSpec {
  circuit_id: string;
  name: string;
  circuit_kind: "ILUMINACAO" | "TOMADAS_USO_GERAL" | "TUE" | "MOTOR" | "DISTRIBUICAO";
  phase_allocation: "F1" | "F2" | "F3" | "F1-F2" | "F2-F3" | "F3-F1" | "F1-F2-F3";
  voltage_v: number;
  load_power_va: number;
  power_factor: number;
  length_m: number;
  installation_method: "A1" | "A2" | "B1" | "B2" | "C" | "D";
  ambient_temp_c: number;
  grouping_count: number;
  is_wet_area: boolean;
  is_external_area: boolean;
  breaker_component_id?: string | null;
  idr_component_id?: string | null;
  cable_phase_mm2: number;
  cable_neutral_mm2?: number | null;
  cable_pe_mm2?: number | null;
  cable_phase_color: CableColor;
  cable_neutral_color?: CableColor | null;
  cable_pe_color?: CableColor | null;
  plan_x_m?: number | null;
  plan_y_m?: number | null;
}

export interface PanelMetadata {
  panel_id: string;
  name: string;
  location: string;
  supply_system:
    | "MONOFASICO_127V"
    | "MONOFASICO_220V"
    | "BIFASICO_127_220V"
    | "TRIFASICO_220_127V"
    | "TRIFASICO_380_220V"
    | "MEDIA_TENSAO_13_8KV";
  grounding_scheme: "TN_S" | "TN_C" | "TN_C_S" | "TT" | "IT";
  nominal_voltage_v: number;
  main_breaker_id?: string | null;
  has_idr: boolean;
  has_dps: boolean;
  has_pe_busbar: boolean;
  has_neutral_busbar: boolean;
  pe_neutral_separated: boolean;
  door_grounding_present: boolean;
  warning_sign_nr10_present: boolean;
  unifilar_diagram_inside_present: boolean;
  ip_rating?: string | null;
}

export interface SpatialCalibration {
  base_dxf_path: string;
  origin_x: number;
  origin_y: number;
  scale_px_per_meter: number;
  calibrated_by_human: boolean;
}

export interface DigitalTwinJSON {
  schema_version: "1.0.0";
  project_id: string;
  inspection_id: string;
  panel: PanelMetadata;
  components: PanelComponent[];
  circuits: CircuitSpec[];
  spatial_calibration?: SpatialCalibration | null;
  source_image_sha256?: string | null;
}

export interface CircuitCalculation {
  circuit_id: string;
  circuit_name: string;
  design_current_ib_a: number;
  breaker_rated_in_a: number | null;
  corrected_ampacity_iz_a: number;
  fct: number;
  fca: number;
  voltage_drop_pct: number;
  coordination_ok: boolean;
  voltage_drop_ok: boolean;
}

export interface ComplianceFinding {
  rule_code: string;
  standard_code: string;
  section_ref: string;
  severity: SeverityLevel;
  target_id: string;
  title: string;
  description: string;
  recommended_action: string;
  suggested_sinapi_category?: string | null;
  suggested_quantity: number;
}

export interface ComplianceReport {
  panel_id: string;
  digital_twin_sha256: string;
  is_compliant: boolean;
  compliance_score_pct: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  circuit_calculations: CircuitCalculation[];
  findings: ComplianceFinding[];
}

export interface ProjectSummary {
  id: string;
  name: string;
  client_name: string;
  installation_type: string;
  supply_system: string;
  grounding_scheme: string;
  nominal_voltage_v: number;
  base_dxf_path?: string | null;
  created_at: string;
}

export interface InspectionSummary {
  id: string;
  project_id: string;
  title: string;
  status: InspectionStatus;
  digital_twin_json?: DigitalTwinJSON | null;
  digital_twin_sha256?: string | null;
  validated_by_name?: string | null;
  validated_by_crea?: string | null;
  art_number?: string | null;
}

export interface JobDispatchResponse {
  job_id: string;
  queue: string;
  status: string;
  sse_url: string;
}

export interface JobProgressEvent {
  job_id: string;
  status: "STARTED" | "PROGRESS" | "COMPLETED" | "FAILED";
  progress_pct: number;
  message: string;
  payload?: Record<string, unknown>;
  timestamp: string;
}

export interface ModelVersionSummary {
  id: string;
  version_tag: string;
  weights_sha256: string;
  map50: number;
  map50_95: number;
  critical_recall_idr: number;
  critical_recall_dps: number;
  critical_recall_disjuntor: number;
  is_active: boolean;
  promoted_at?: string | null;
  created_at: string;
}
