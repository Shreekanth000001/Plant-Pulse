/**
 * PlantPulse Industrial Telemetry Types
 */

export type MachineState = "RUNNING" | "IDLE" | "FAULT" | "TESTING" | string;

export type ReadingValue = number | string | boolean | null;

export type Readings = Record<string, ReadingValue>;

export interface SignalDefinition {
  signal_code: string;
  name: string;
  unit: string;
  data_type: string;
  is_setpoint?: boolean;
  setpoint_signal_code?: string | null;
  normal_min?: number | null;
  normal_max?: number | null;
  warn_min?: number | null;
  warn_max?: number | null;
  alarm_min?: number | null;
  alarm_max?: number | null;
  display_order?: number;
}

export interface MachineDefinition {
  machine_code: string;
  name: string;
  machine_type?: string | null;
  display_order?: number;
  signals: SignalDefinition[];
}

export interface AreaDefinition {
  area_code: string;
  name: string;
  display_order?: number;
  machines: MachineDefinition[];
}

export interface PlantSummary {
  plant_id: string;
  name: string;
  timezone: string;
  has_viewer_token: boolean;
  enabled_modules: string[];
}

export interface PublicPlantDefinition {
  plant_id: string;
  name: string;
  timezone: string;
  has_viewer_token: boolean;
  enabled_modules: string[];
  areas: AreaDefinition[];
}

export interface PlantMachineSignalValue {
  value: number | string | boolean | null;
  value_num?: number | null;
  value_text?: string | null;
  device_timestamp?: string | null;
}

export interface PlantMachineLatest {
  machine_code: string;
  area_code: string;
  name: string;
  machine_type?: string | null;
  state: MachineState;
  sub_state?: string | null;
  last_seen_at?: string | null;
  signals: Record<string, PlantMachineSignalValue>;
}

export interface MachineStatus {
  machine_id: string;
  name?: string;
  area_code?: string;
  sub_facility: string;
  machine_state: MachineState;
  phase?: string | null;
  starved: boolean;
  current_unit_id?: string | null;
  vibration?: number | null;
  vibration_wear_level?: number | null;
  good_count?: number;
  reject_count?: number;
  signals?: Record<string, PlantMachineSignalValue>;
  extra: Readings;
  timestamp?: string | null;
}

export interface TelemetryPayload {
  machine_id: string;
  name?: string;
  machine_state?: MachineState;
  phase?: string;
  starved?: boolean;
  current_unit?: string | null;
  current_unit_id?: string | null;
  vibration?: number;
  vibration_wear_level?: number;
  good_count?: number;
  reject_count?: number;
  stage_event?: StageEventPayload | null;
  last_result?: QCResultPayload | null;
  [key: string]: ReadingValue | StageEventPayload | QCResultPayload | undefined;
}

export interface StageEventPayload {
  unit_id: string;
  sub_facility: string;
  machine_id: string;
  entered_at?: number | string | null;
  exited_at?: number | string | null;
  outcome: "ok" | "flagged" | string;
  anomaly_score: number;
  readings: Record<string, number | string | boolean>;
}

export interface QCResultPayload {
  unit_id: string;
  machine_id?: string;
  outcome: "pass" | "fail";
  probability: number;
  defect_type?: string | null;
  attributed_stage?: string | null;
  tested_at?: string | null;
}

export interface BackendQueueDepths {
  casting?: number;
  assembly?: number;
  qc?: number;
  [key: string]: number | undefined;
}

export interface WebSocketMessage {
  topic: string;
  payload: TelemetryPayload | StageEventPayload | QCResultPayload | BackendQueueDepths;
}

export function isTelemetryMessage(
  msg: WebSocketMessage
): msg is WebSocketMessage & { payload: TelemetryPayload } {
  return msg.topic.endsWith("/telemetry");
}

export function isQueueDepthsMessage(
  msg: WebSocketMessage
): msg is WebSocketMessage & { payload: BackendQueueDepths } {
  return msg.topic === "factory/queue_depths" || msg.topic.includes("/queue_depths");
}

export function isReadingValue(v: unknown): v is ReadingValue {
  return (
    v === null ||
    typeof v === "number" ||
    typeof v === "string" ||
    typeof v === "boolean"
  );
}

export interface StageHistoryItem {
  sub_facility: string;
  machine_id: string;
  outcome: "ok" | "flagged" | string;
  anomaly_score: number;
  readings: Record<string, number | string | boolean>;
  entered_at: string | null;
  exited_at: string | null;
}

export interface QCResultItem {
  outcome: "pass" | "fail" | string;
  probability: number;
  defect_type: string | null;
  attributed_stage: string | null;
  tested_at: string | null;
}

export interface UnitHistoryResponse {
  unit_id: string;
  status: "in_progress" | "passed" | "failed" | string;
  created_at: string | null;
  stages: StageHistoryItem[];
  qc_result: QCResultItem | null;
}

export interface RecentUnitItem {
  unit_id: string;
  status: "in_progress" | "passed" | "failed" | string;
  created_at: string | null;
}

export interface DefectRateByHour {
  hour: string;
  total_tested: number;
  failed: number;
  defect_rate: number;
}

export interface DefectRateByStage {
  stage: string;
  failures: number;
}

export interface QueueHandoffs {
  housingToCasting: number;
  castingToAssembly: number;
  assemblyToQc: number;
}

export function mapBackendQueueDepths(
  data: BackendQueueDepths
): QueueHandoffs {
  const actual =
    data && typeof (data as Record<string, unknown>).payload === "object"
      ? ((data as Record<string, unknown>).payload as BackendQueueDepths)
      : data || {};
  return {
    housingToCasting: Number(actual.casting ?? 0),
    castingToAssembly: Number(actual.assembly ?? 0),
    assemblyToQc: Number(actual.qc ?? 0),
  };
}

export interface SignalHistoryPoint {
  bucket_start: string;
  count: number | null;
  avg: number | null;
  min: number | null;
  max: number | null;
  last: number | null;
}

export interface SignalHistoryResponse {
  plant_id: string;
  machine_code: string;
  signal_code: string;
  start: string;
  end: string;
  bucket_sec: number;
  total_points: number;
  data: SignalHistoryPoint[];
}
