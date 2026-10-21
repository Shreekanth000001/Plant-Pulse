"use client";

import React, { useState, useReducer } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAdminAuth } from "../../layout";
import {
  createAdminPlant,
  credentialModalReducer,
  initialCredentialModalState,
  mapFastApi422Errors,
  formatAdminErrorMessage,
  AdminApiError,
  type FastApiValidationErrorDetail,
} from "../../../../lib/admin-api";
import { AdminCredentialsModal } from "../../../../components/admin/AdminCredentialsModal";

interface FormSignal {
  signal_code: string;
  name: string;
  unit: string;
  data_type: "float" | "int" | "bool" | "string";
  warn_min: string;
  warn_max: string;
  alarm_min: string;
  alarm_max: string;
  normal_min: string;
  normal_max: string;
}

interface FormMachine {
  machine_code: string;
  name: string;
  machine_type: string;
  signals: FormSignal[];
}

interface FormArea {
  area_code: string;
  name: string;
  machines: FormMachine[];
}

export default function NewPlantPage() {
  const router = useRouter();
  const { adminToken } = useAdminAuth();

  const [plantId, setPlantId] = useState("");
  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [viewerToken, setViewerToken] = useState("");

  const [areas, setAreas] = useState<FormArea[]>([
    {
      area_code: "production",
      name: "Main Production Area",
      machines: [
        {
          machine_code: "unit_01",
          name: "Processing Unit 1",
          machine_type: "standard",
          signals: [
            {
              signal_code: "temperature",
              name: "Operating Temperature",
              unit: "°C",
              data_type: "float",
              normal_min: "20",
              normal_max: "25",
              warn_min: "15",
              warn_max: "30",
              alarm_min: "10",
              alarm_max: "35",
            },
          ],
        },
      ],
    },
  ]);

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Credential Modal State Machine
  const [modalState, dispatchModal] = useReducer(
    credentialModalReducer,
    initialCredentialModalState
  );

  const handleAddArea = () => {
    const nextIdx = areas.length + 1;
    setAreas([
      ...areas,
      {
        area_code: `area_${nextIdx}`,
        name: `Sub-Area ${nextIdx}`,
        machines: [
          {
            machine_code: `mach_${nextIdx}_1`,
            name: `Machine 1`,
            machine_type: "standard",
            signals: [
              {
                signal_code: "pressure",
                name: "Pressure",
                unit: "bar",
                data_type: "float",
                normal_min: "",
                normal_max: "",
                warn_min: "",
                warn_max: "",
                alarm_min: "",
                alarm_max: "",
              },
            ],
          },
        ],
      },
    ]);
  };

  const handleRemoveArea = (aIdx: number) => {
    if (areas.length <= 1) return;
    setAreas(areas.filter((_, idx) => idx !== aIdx));
  };

  const handleAddMachine = (aIdx: number) => {
    const currentArea = areas[aIdx];
    const nextIdx = currentArea.machines.length + 1;
    const newMachine: FormMachine = {
      machine_code: `mach_${nextIdx}`,
      name: `Machine ${nextIdx}`,
      machine_type: "standard",
      signals: [
        {
          signal_code: "flow_rate",
          name: "Flow Rate",
          unit: "L/min",
          data_type: "float",
          normal_min: "",
          normal_max: "",
          warn_min: "",
          warn_max: "",
          alarm_min: "",
          alarm_max: "",
        },
      ],
    };
    const nextAreas = [...areas];
    nextAreas[aIdx] = {
      ...currentArea,
      machines: [...currentArea.machines, newMachine],
    };
    setAreas(nextAreas);
  };

  const handleRemoveMachine = (aIdx: number, mIdx: number) => {
    const currentArea = areas[aIdx];
    if (currentArea.machines.length <= 1) return;
    const nextAreas = [...areas];
    nextAreas[aIdx] = {
      ...currentArea,
      machines: currentArea.machines.filter((_, idx) => idx !== mIdx),
    };
    setAreas(nextAreas);
  };

  const handleAddSignal = (aIdx: number, mIdx: number) => {
    const nextAreas = [...areas];
    const currentMach = nextAreas[aIdx].machines[mIdx];
    const nextIdx = currentMach.signals.length + 1;
    currentMach.signals.push({
      signal_code: `signal_${nextIdx}`,
      name: `Signal ${nextIdx}`,
      unit: "",
      data_type: "float",
      normal_min: "",
      normal_max: "",
      warn_min: "",
      warn_max: "",
      alarm_min: "",
      alarm_max: "",
    });
    setAreas(nextAreas);
  };

  const handleRemoveSignal = (aIdx: number, mIdx: number, sIdx: number) => {
    const nextAreas = [...areas];
    const currentMach = nextAreas[aIdx].machines[mIdx];
    if (currentMach.signals.length <= 1) return;
    currentMach.signals = currentMach.signals.filter((_, idx) => idx !== sIdx);
    setAreas(nextAreas);
  };

  const parseNumber = (val: string): number | null => {
    const trimmed = val.trim();
    if (!trimmed) return null;
    const parsed = parseFloat(trimmed);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setGeneralError(null);
    setFieldErrors({});
    setIsSubmitting(true);

    const payload = {
      plant_id: plantId.trim(),
      name: name.trim(),
      timezone: timezone.trim() || "UTC",
      viewer_token: viewerToken.trim() || null,
      enabled_modules: ["core", "alarms"],
      areas: areas.map((area, aIdx) => ({
        area_code: area.area_code.trim(),
        name: area.name.trim(),
        display_order: aIdx + 1,
        machines: area.machines.map((mach, mIdx) => ({
          machine_code: mach.machine_code.trim(),
          name: mach.name.trim(),
          machine_type: mach.machine_type.trim() || "standard",
          display_order: mIdx + 1,
          signals: mach.signals.map((sig, sIdx) => ({
            signal_code: sig.signal_code.trim(),
            name: sig.name.trim(),
            unit: sig.unit.trim(),
            data_type: sig.data_type,
            display_order: sIdx + 1,
            normal_min: parseNumber(sig.normal_min),
            normal_max: parseNumber(sig.normal_max),
            warn_min: parseNumber(sig.warn_min),
            warn_max: parseNumber(sig.warn_max),
            alarm_min: parseNumber(sig.alarm_min),
            alarm_max: parseNumber(sig.alarm_max),
          })),
        })),
      })),
    };

    try {
      const res = await createAdminPlant(adminToken, payload);
      // Surface one-time device credentials in secure modal
      if (res.one_time_device_credentials && res.one_time_device_credentials.length > 0) {
        dispatchModal({
          type: "OPEN_CREDENTIALS",
          source: "create",
          credentials: res.one_time_device_credentials,
          brokerReloaded: res.broker_reloaded,
        });
      } else {
        router.push("/admin");
      }
    } catch (err: unknown) {
      if (err instanceof AdminApiError) {
        const validationDetails = (
          err as unknown as { validationErrors?: FastApiValidationErrorDetail[] }
        ).validationErrors;
        if (validationDetails) {
          const mapped = mapFastApi422Errors(validationDetails);
          setFieldErrors(mapped);
          setGeneralError("Validation failed. Please correct highlighted fields.");
        } else {
          setGeneralError(formatAdminErrorMessage(err));
        }
      } else {
        setGeneralError("Failed to create plant definition. Verify inputs and server state.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleModalClose = () => {
    dispatchModal({ type: "CLOSE_CREDENTIALS" });
    router.push("/admin");
  };

  return (
    <div className="flex flex-col gap-6 max-w-5xl mx-auto py-2">
      {/* Credential Modal */}
      <AdminCredentialsModal
        isOpen={modalState.isOpen}
        source={modalState.source}
        credentials={modalState.credentials}
        brokerReloaded={modalState.brokerReloaded}
        onClose={handleModalClose}
      />

      {/* Breadcrumb & Navigation */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 text-xs text-slate-500 font-medium">
          <Link href="/admin" className="hover:text-slate-900 transition-colors">
            ← Back to Plant Registry
          </Link>
          <span>/</span>
          <span className="text-slate-900 font-semibold">Register New Plant</span>
        </div>
      </div>

      {/* Header Banner */}
      <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-xs flex flex-col gap-2">
        <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-3">
          <span>🏭</span>
          <span>Register New Plant Facility</span>
        </h1>
        <p className="text-xs sm:text-sm text-slate-500 max-w-2xl leading-relaxed">
          Define facility metadata, topology (areas, machines), and telemetry signal thresholds. Initial device MQTT credentials will be generated and displayed once.
        </p>
      </div>

      {generalError && (
        <div
          role="alert"
          className="p-4 rounded-2xl bg-rose-50 border border-rose-300 text-rose-900 text-xs flex items-center gap-3 font-medium"
        >
          <span className="text-rose-600 font-bold text-base">✕</span>
          <span>{generalError}</span>
        </div>
      )}

      {/* Main Creation Form */}
      <form onSubmit={handleSubmit} className="flex flex-col gap-8">
        {/* Plant Metadata */}
        <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-xs flex flex-col gap-6">
          <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400 border-b border-slate-100 pb-3">
            Plant Metadata & Access
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="plant-id-input"
                className="text-xs font-semibold text-slate-700 flex items-center justify-between"
              >
                <span>Plant ID</span>
                <span className="text-[10px] text-slate-400 font-mono">^[a-z0-9_]&#123;3,64&#125;$</span>
              </label>
              <input
                id="plant-id-input"
                type="text"
                value={plantId}
                onChange={(e) => setPlantId(e.target.value)}
                placeholder="e.g. plant_ro_skid_01"
                required
                className={`w-full px-4 py-2.5 rounded-xl border font-mono text-xs text-slate-900 bg-slate-50 focus:bg-white focus:outline-hidden focus:ring-2 focus:ring-blue-500 transition-colors ${
                  fieldErrors["plant_id"] ? "border-rose-400 bg-rose-50/50" : "border-slate-300"
                }`}
              />
              {fieldErrors["plant_id"] && (
                <span className="text-[11px] text-rose-600 font-medium">
                  {fieldErrors["plant_id"]}
                </span>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="plant-name-input" className="text-xs font-semibold text-slate-700">
                Facility Display Name
              </label>
              <input
                id="plant-name-input"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Reverse Osmosis Skid 01"
                required
                className={`w-full px-4 py-2.5 rounded-xl border text-xs text-slate-900 bg-slate-50 focus:bg-white focus:outline-hidden focus:ring-2 focus:ring-blue-500 transition-colors ${
                  fieldErrors["name"] ? "border-rose-400 bg-rose-50/50" : "border-slate-300"
                }`}
              />
              {fieldErrors["name"] && (
                <span className="text-[11px] text-rose-600 font-medium">
                  {fieldErrors["name"]}
                </span>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="plant-tz-input" className="text-xs font-semibold text-slate-700">
                Timezone
              </label>
              <input
                id="plant-tz-input"
                type="text"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                placeholder="e.g. UTC, America/Chicago"
                required
                className="w-full px-4 py-2.5 rounded-xl border border-slate-300 text-xs text-slate-900 bg-slate-50 focus:bg-white focus:outline-hidden focus:ring-2 focus:ring-blue-500 transition-colors"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="plant-token-input" className="text-xs font-semibold text-slate-700">
                Viewer Access Token (Optional)
              </label>
              <input
                id="plant-token-input"
                type="text"
                value={viewerToken}
                onChange={(e) => setViewerToken(e.target.value)}
                placeholder="Leave blank for public facility"
                className="w-full px-4 py-2.5 rounded-xl border border-slate-300 text-xs text-slate-900 bg-slate-50 focus:bg-white focus:outline-hidden focus:ring-2 focus:ring-blue-500 transition-colors"
              />
              <span className="text-[11px] text-slate-400">
                If provided, operators require this token to view live streams. (Note: cannot be removed after creation).
              </span>
            </div>
          </div>
        </div>

        {/* Areas, Machines, Signals */}
        <div className="flex flex-col gap-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400">
              Plant Topology & Signals ({areas.length} Areas)
            </h2>
            <button
              type="button"
              onClick={handleAddArea}
              className="px-3.5 py-1.5 rounded-xl bg-blue-50 hover:bg-blue-100 text-blue-700 text-xs font-bold border border-blue-200 transition-colors flex items-center gap-1.5"
            >
              <span>+</span>
              <span>Add Production Area</span>
            </button>
          </div>

          {areas.map((area, aIdx) => (
            <div
              key={aIdx}
              className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-xs flex flex-col gap-6"
            >
              <div className="flex items-center justify-between border-b border-slate-100 pb-4">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold text-xs">
                    {aIdx + 1}
                  </div>
                  <span className="text-sm font-bold text-slate-800">
                    Area #{aIdx + 1}: {area.name || "Untitled Area"}
                  </span>
                </div>
                {areas.length > 1 && (
                  <button
                    type="button"
                    onClick={() => handleRemoveArea(aIdx)}
                    className="text-xs text-rose-600 hover:text-rose-800 font-semibold px-2.5 py-1 rounded-lg hover:bg-rose-50 transition-colors"
                  >
                    Remove Area
                  </button>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="flex flex-col gap-1">
                  <label className="text-xs font-semibold text-slate-600">Area Code</label>
                  <input
                    type="text"
                    value={area.area_code}
                    onChange={(e) => {
                      const next = [...areas];
                      next[aIdx].area_code = e.target.value;
                      setAreas(next);
                    }}
                    required
                    placeholder="e.g. membrane_casting"
                    className={`w-full px-3.5 py-2 rounded-xl border font-mono text-xs text-slate-900 bg-slate-50 ${
                      fieldErrors[`areas.${aIdx}.area_code`] ? "border-rose-400 bg-rose-50/50" : "border-slate-300"
                    }`}
                  />
                  {fieldErrors[`areas.${aIdx}.area_code`] && (
                    <span className="text-[11px] text-rose-600 font-medium">
                      {fieldErrors[`areas.${aIdx}.area_code`]}
                    </span>
                  )}
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-xs font-semibold text-slate-600">Area Name</label>
                  <input
                    type="text"
                    value={area.name}
                    onChange={(e) => {
                      const next = [...areas];
                      next[aIdx].name = e.target.value;
                      setAreas(next);
                    }}
                    required
                    placeholder="e.g. Membrane Casting Line"
                    className="w-full px-3.5 py-2 rounded-xl border border-slate-300 text-xs text-slate-900 bg-slate-50"
                  />
                </div>
              </div>

              {/* Machines inside area */}
              <div className="flex flex-col gap-5 pt-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-600 uppercase tracking-wider">
                    Machines in Area ({area.machines.length})
                  </span>
                  <button
                    type="button"
                    onClick={() => handleAddMachine(aIdx)}
                    className="text-xs font-bold text-blue-600 hover:text-blue-800"
                  >
                    + Add Machine
                  </button>
                </div>

                {area.machines.map((mach, mIdx) => (
                  <div
                    key={mIdx}
                    className="bg-slate-50/70 border border-slate-200/80 rounded-2xl p-5 flex flex-col gap-4"
                  >
                    <div className="flex items-center justify-between border-b border-slate-200 pb-3">
                      <span className="text-xs font-bold text-slate-700">
                        Machine #{mIdx + 1}: {mach.name || mach.machine_code}
                      </span>
                      {area.machines.length > 1 && (
                        <button
                          type="button"
                          onClick={() => handleRemoveMachine(aIdx, mIdx)}
                          className="text-[11px] text-rose-600 hover:text-rose-800 font-medium"
                        >
                          Remove Machine
                        </button>
                      )}
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="flex flex-col gap-1">
                        <label className="text-[11px] font-semibold text-slate-500">
                          Machine Code
                        </label>
                        <input
                          type="text"
                          value={mach.machine_code}
                          onChange={(e) => {
                            const next = [...areas];
                            next[aIdx].machines[mIdx].machine_code = e.target.value;
                            setAreas(next);
                          }}
                          required
                          placeholder="e.g. cs_01"
                          className={`w-full px-3 py-1.5 rounded-lg border font-mono text-xs text-slate-900 bg-white ${
                            fieldErrors[`areas.${aIdx}.machines.${mIdx}.machine_code`]
                              ? "border-rose-400 bg-rose-50"
                              : "border-slate-300"
                          }`}
                        />
                        {fieldErrors[`areas.${aIdx}.machines.${mIdx}.machine_code`] && (
                          <span className="text-[10px] text-rose-600">
                            {fieldErrors[`areas.${aIdx}.machines.${mIdx}.machine_code`]}
                          </span>
                        )}
                      </div>

                      <div className="flex flex-col gap-1">
                        <label className="text-[11px] font-semibold text-slate-500">
                          Machine Name
                        </label>
                        <input
                          type="text"
                          value={mach.name}
                          onChange={(e) => {
                            const next = [...areas];
                            next[aIdx].machines[mIdx].name = e.target.value;
                            setAreas(next);
                          }}
                          required
                          placeholder="e.g. Casting Machine 1"
                          className="w-full px-3 py-1.5 rounded-lg border border-slate-300 text-xs text-slate-900 bg-white"
                        />
                      </div>
                    </div>

                    {/* Signals in machine */}
                    <div className="flex flex-col gap-3 pt-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-bold text-slate-500 uppercase">
                          Signals ({mach.signals.length})
                        </span>
                        <button
                          type="button"
                          onClick={() => handleAddSignal(aIdx, mIdx)}
                          className="text-[11px] font-bold text-blue-600 hover:text-blue-800"
                        >
                          + Add Signal
                        </button>
                      </div>

                      {mach.signals.map((sig, sIdx) => (
                        <div
                          key={sIdx}
                          className="bg-white border border-slate-200 rounded-xl p-3.5 flex flex-col gap-3"
                        >
                          <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                            <span className="text-xs font-semibold text-slate-700 font-mono">
                              {sig.signal_code || `Signal #${sIdx + 1}`} ({sig.data_type})
                            </span>
                            {mach.signals.length > 1 && (
                              <button
                                type="button"
                                onClick={() => handleRemoveSignal(aIdx, mIdx, sIdx)}
                                className="text-[10px] text-rose-600 hover:text-rose-800"
                              >
                                Remove Signal
                              </button>
                            )}
                          </div>

                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                            <div className="flex flex-col gap-0.5">
                              <label className="text-[10px] text-slate-500">Signal Code</label>
                              <input
                                type="text"
                                value={sig.signal_code}
                                onChange={(e) => {
                                  const next = [...areas];
                                  next[aIdx].machines[mIdx].signals[sIdx].signal_code =
                                    e.target.value;
                                  setAreas(next);
                                }}
                                required
                                placeholder="temp_actual"
                                className="w-full px-2.5 py-1 rounded-md border border-slate-300 text-xs font-mono"
                              />
                            </div>

                            <div className="flex flex-col gap-0.5">
                              <label className="text-[10px] text-slate-500">Signal Name</label>
                              <input
                                type="text"
                                value={sig.name}
                                onChange={(e) => {
                                  const next = [...areas];
                                  next[aIdx].machines[mIdx].signals[sIdx].name = e.target.value;
                                  setAreas(next);
                                }}
                                required
                                placeholder="Temperature"
                                className="w-full px-2.5 py-1 rounded-md border border-slate-300 text-xs"
                              />
                            </div>

                            <div className="flex flex-col gap-0.5">
                              <label className="text-[10px] text-slate-500">Unit</label>
                              <input
                                type="text"
                                value={sig.unit}
                                onChange={(e) => {
                                  const next = [...areas];
                                  next[aIdx].machines[mIdx].signals[sIdx].unit = e.target.value;
                                  setAreas(next);
                                }}
                                placeholder="°C"
                                className="w-full px-2.5 py-1 rounded-md border border-slate-300 text-xs"
                              />
                            </div>

                            <div className="flex flex-col gap-0.5">
                              <label className="text-[10px] text-slate-500">Data Type</label>
                              <select
                                value={sig.data_type}
                                onChange={(e) => {
                                  const next = [...areas];
                                  next[aIdx].machines[mIdx].signals[sIdx].data_type = e.target
                                    .value as FormSignal["data_type"];
                                  setAreas(next);
                                }}
                                className="w-full px-2.5 py-1 rounded-md border border-slate-300 text-xs bg-white"
                              >
                                <option value="float">float</option>
                                <option value="int">int</option>
                                <option value="bool">bool</option>
                                <option value="string">string</option>
                              </select>
                            </div>
                          </div>

                          {/* Thresholds */}
                          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 pt-1 border-t border-slate-100">
                            <div>
                              <label className="text-[9px] text-slate-400 font-mono">
                                normal_min
                              </label>
                              <input
                                type="text"
                                value={sig.normal_min}
                                onChange={(e) => {
                                  const next = [...areas];
                                  next[aIdx].machines[mIdx].signals[sIdx].normal_min = e.target.value;
                                  setAreas(next);
                                }}
                                placeholder="min"
                                className="w-full px-2 py-0.5 rounded-md border border-slate-200 text-xs font-mono text-center"
                              />
                            </div>
                            <div>
                              <label className="text-[9px] text-slate-400 font-mono">
                                normal_max
                              </label>
                              <input
                                type="text"
                                value={sig.normal_max}
                                onChange={(e) => {
                                  const next = [...areas];
                                  next[aIdx].machines[mIdx].signals[sIdx].normal_max = e.target.value;
                                  setAreas(next);
                                }}
                                placeholder="max"
                                className="w-full px-2 py-0.5 rounded-md border border-slate-200 text-xs font-mono text-center"
                              />
                            </div>
                            <div>
                              <label className="text-[9px] text-amber-600 font-mono">warn_min</label>
                              <input
                                type="text"
                                value={sig.warn_min}
                                onChange={(e) => {
                                  const next = [...areas];
                                  next[aIdx].machines[mIdx].signals[sIdx].warn_min = e.target.value;
                                  setAreas(next);
                                }}
                                placeholder="min"
                                className="w-full px-2 py-0.5 rounded-md border border-amber-200 text-xs font-mono text-center"
                              />
                            </div>
                            <div>
                              <label className="text-[9px] text-amber-600 font-mono">warn_max</label>
                              <input
                                type="text"
                                value={sig.warn_max}
                                onChange={(e) => {
                                  const next = [...areas];
                                  next[aIdx].machines[mIdx].signals[sIdx].warn_max = e.target.value;
                                  setAreas(next);
                                }}
                                placeholder="max"
                                className="w-full px-2 py-0.5 rounded-md border border-amber-200 text-xs font-mono text-center"
                              />
                            </div>
                            <div>
                              <label className="text-[9px] text-rose-600 font-mono">alarm_min</label>
                              <input
                                type="text"
                                value={sig.alarm_min}
                                onChange={(e) => {
                                  const next = [...areas];
                                  next[aIdx].machines[mIdx].signals[sIdx].alarm_min = e.target.value;
                                  setAreas(next);
                                }}
                                placeholder="min"
                                className="w-full px-2 py-0.5 rounded-md border border-rose-200 text-xs font-mono text-center"
                              />
                            </div>
                            <div>
                              <label className="text-[9px] text-rose-600 font-mono">alarm_max</label>
                              <input
                                type="text"
                                value={sig.alarm_max}
                                onChange={(e) => {
                                  const next = [...areas];
                                  next[aIdx].machines[mIdx].signals[sIdx].alarm_max = e.target.value;
                                  setAreas(next);
                                }}
                                placeholder="max"
                                className="w-full px-2 py-0.5 rounded-md border border-rose-200 text-xs font-mono text-center"
                              />
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Submit Actions */}
        <div className="flex items-center justify-between gap-4 pt-4 border-t border-slate-200">
          <Link
            href="/admin"
            className="px-5 py-2.5 rounded-xl text-xs font-bold text-slate-600 hover:text-slate-900 border border-slate-300 hover:bg-slate-50 transition-colors"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={isSubmitting}
            className="px-6 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs font-bold transition-all shadow-xs flex items-center gap-2"
          >
            {isSubmitting ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                <span>Creating Facility...</span>
              </>
            ) : (
              <>
                <span>Create Plant & Generate Credentials →</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
