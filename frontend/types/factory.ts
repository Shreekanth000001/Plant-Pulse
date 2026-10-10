/**
 * PlantPulse Industrial Telemetry Types
 */

export type SubFacilityType = "housing" | "casting" | "assembly" | "qc";

export type MachineState = "RUNNING" | "IDLE" | "FAULT" | "TESTING" | string;

export type ReadingValue = number | string | boolean | null;

export type Readings = Record<string, ReadingValue>;

export interface MachineStatus {
  machine_id: string;
  name?: string;
  sub_facility: SubFacilityType | string;
  machine_state: MachineState;
  phase?: string | null;
  starved: boolean;
  current_unit_id?: string | null;
  vibration?: number | null;
  vibration_wear_level?: number | null;
  good_count?: number;
  reject_count?: number;
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

export interface WebSocketMessage {
  topic: string;
  payload: TelemetryPayload | StageEventPayload | QCResultPayload;
}

export function isTelemetryMessage(
  msg: WebSocketMessage
): msg is WebSocketMessage & { payload: TelemetryPayload } {
  return msg.topic.endsWith("/telemetry");
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

export interface MachineConfigMeta {
  id: string;
  name: string;
  stage: SubFacilityType;
}

export const KNOWN_MACHINES: Record<string, { name: string; stage: SubFacilityType }> = {
  hm_01: { name: "Housing Molder 1", stage: "housing" },
  hm_02: { name: "Housing Molder 2", stage: "housing" },
  hm_03: { name: "Housing Molder 3", stage: "housing" },
  hm_04: { name: "Housing Molder 4", stage: "housing" },
  cs_01: { name: "Casting Machine 1", stage: "casting" },
  cs_02: { name: "Casting Machine 2", stage: "casting" },
  cs_03: { name: "Casting Machine 3", stage: "casting" },
  am_01: { name: "Assembly Station 1", stage: "assembly" },
  am_02: { name: "Assembly Station 2", stage: "assembly" },
  am_03: { name: "Assembly Station 3", stage: "assembly" },
  qc_01: { name: "QC Test Station", stage: "qc" },
};
