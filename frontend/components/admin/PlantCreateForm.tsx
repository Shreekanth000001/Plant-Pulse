"use client";

import React, { useState } from "react";
import {
  mapFastApi422Errors,
  formatAdminErrorMessage,
  AdminApiError,
  parsePlantJson,
  validatePlantDefinitionAdvisory,
  type FastApiValidationErrorDetail,
} from "../../lib/admin-api";

export interface FormSignal {
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

export interface FormMachine {
  machine_code: string;
  name: string;
  machine_type: string;
  signals: FormSignal[];
}

export interface FormArea {
  area_code: string;
  name: string;
  machines: FormMachine[];
}

export interface PlantCreateFormProps {
  onSubmit: (payload: Record<string, unknown>) => Promise<unknown>;
  onSuccess: (result: unknown) => void;
  onCancel?: () => void;
  isSelfService?: boolean;
}

function parseNumber(val: string): number | null {
  if (!val || val.trim() === "") return null;
  const num = parseFloat(val);
  return Number.isNaN(num) ? null : num;
}

export function PlantCreateForm({
  onSubmit,
  onSuccess,
  onCancel,
  isSelfService = false,
}: PlantCreateFormProps) {
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

  // JSON Import State
  const [jsonInputText, setJsonInputText] = useState("");
  const [jsonSyntaxError, setJsonSyntaxError] = useState<string | null>(null);
  const [advisoryErrors, setAdvisoryErrors] = useState<Record<string, string>>({});
  const [advisoryWarnings, setAdvisoryWarnings] = useState<string[]>([]);
  const [importStatusMessage, setImportStatusMessage] = useState<string | null>(null);

  const applyJsonContent = (rawText: string) => {
    setJsonSyntaxError(null);
    setAdvisoryErrors({});
    setAdvisoryWarnings([]);
    setImportStatusMessage(null);
    setGeneralError(null);

    const trimmed = rawText.trim();
    if (!trimmed) {
      setJsonSyntaxError("Please paste JSON or choose a JSON file to import.");
      return;
    }

    const parseResult = parsePlantJson(trimmed);
    if (!parseResult.success || !parseResult.data) {
      setJsonSyntaxError(parseResult.error || "Invalid JSON syntax.");
      return;
    }

    const data = parseResult.data;
    const advisory = validatePlantDefinitionAdvisory(data);
    setAdvisoryErrors(advisory.errors);
    setAdvisoryWarnings(advisory.warnings);

    setFieldErrors(advisory.errors);

    if (typeof data.plant_id === "string") setPlantId(data.plant_id);
    if (typeof data.name === "string") setName(data.name);
    if (typeof data.timezone === "string") setTimezone(data.timezone);
    if (typeof data.viewer_token === "string" && !isSelfService) {
      setViewerToken(data.viewer_token);
    }

    if (Array.isArray(data.areas) && data.areas.length > 0) {
      const mappedAreas: FormArea[] = data.areas.map((a: unknown, aIdx: number) => {
        const area = (a || {}) as Record<string, unknown>;
        const rawMachines = Array.isArray(area.machines) ? area.machines : [];
        return {
          area_code: typeof area.area_code === "string" ? area.area_code : `area_${aIdx + 1}`,
          name: typeof area.name === "string" ? area.name : `Area ${aIdx + 1}`,
          machines:
            rawMachines.length > 0
              ? rawMachines.map((m: unknown, mIdx: number) => {
                  const mach = (m || {}) as Record<string, unknown>;
                  const rawSignals = Array.isArray(mach.signals) ? mach.signals : [];
                  return {
                    machine_code:
                      typeof mach.machine_code === "string"
                        ? mach.machine_code
                        : `mach_${mIdx + 1}`,
                    name: typeof mach.name === "string" ? mach.name : `Machine ${mIdx + 1}`,
                    machine_type:
                      typeof mach.machine_type === "string"
                        ? mach.machine_type
                        : "standard",
                    signals:
                      rawSignals.length > 0
                        ? rawSignals.map((s: unknown, sIdx: number) => {
                            const sig = (s || {}) as Record<string, unknown>;
                            const dType =
                              sig.data_type === "int" ||
                              sig.data_type === "bool" ||
                              sig.data_type === "string"
                                ? sig.data_type
                                : "float";
                            return {
                              signal_code:
                                typeof sig.signal_code === "string"
                                  ? sig.signal_code
                                  : `signal_${sIdx + 1}`,
                              name:
                                typeof sig.name === "string" ? sig.name : `Signal ${sIdx + 1}`,
                              unit: typeof sig.unit === "string" ? sig.unit : "",
                              data_type: dType as "float" | "int" | "bool" | "string",
                              normal_min: sig.normal_min != null ? String(sig.normal_min) : "",
                              normal_max: sig.normal_max != null ? String(sig.normal_max) : "",
                              warn_min: sig.warn_min != null ? String(sig.warn_min) : "",
                              warn_max: sig.warn_max != null ? String(sig.warn_max) : "",
                              alarm_min: sig.alarm_min != null ? String(sig.alarm_min) : "",
                              alarm_max: sig.alarm_max != null ? String(sig.alarm_max) : "",
                            };
                          })
                        : [
                            {
                              signal_code: "temperature",
                              name: "Temperature",
                              unit: "°C",
                              data_type: "float" as const,
                              normal_min: "20",
                              normal_max: "25",
                              warn_min: "15",
                              warn_max: "30",
                              alarm_min: "10",
                              alarm_max: "35",
                            },
                          ],
                  };
                })
              : [
                  {
                    machine_code: "unit_01",
                    name: "Unit 01",
                    machine_type: "standard",
                    signals: [
                      {
                        signal_code: "temperature",
                        name: "Temperature",
                        unit: "°C",
                        data_type: "float" as const,
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
        };
      });
      setAreas(mappedAreas);
    }

    if (advisory.valid) {
      setImportStatusMessage(
        "Plant definition loaded from JSON into form. Please review the configuration below before submitting."
      );
    } else {
      setImportStatusMessage(
        "Plant definition loaded into form with advisory warnings. Please review the highlighted fields below."
      );
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result;
      if (typeof content === "string") {
        setJsonInputText(content);
        applyJsonContent(content);
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

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
    const currentMach = areas[aIdx].machines[mIdx];
    const nextIdx = currentMach.signals.length + 1;
    const newSignal: FormSignal = {
      signal_code: `sig_${nextIdx}`,
      name: `Signal ${nextIdx}`,
      unit: "",
      data_type: "float",
      normal_min: "",
      normal_max: "",
      warn_min: "",
      warn_max: "",
      alarm_min: "",
      alarm_max: "",
    };
    const nextAreas = [...areas];
    nextAreas[aIdx].machines[mIdx] = {
      ...currentMach,
      signals: [...currentMach.signals, newSignal],
    };
    setAreas(nextAreas);
  };

  const handleRemoveSignal = (aIdx: number, mIdx: number, sIdx: number) => {
    const currentMach = areas[aIdx].machines[mIdx];
    if (currentMach.signals.length <= 1) return;
    const nextAreas = [...areas];
    nextAreas[aIdx].machines[mIdx] = {
      ...currentMach,
      signals: currentMach.signals.filter((_, idx) => idx !== sIdx),
    };
    setAreas(nextAreas);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setGeneralError(null);
    setFieldErrors({});

    const clientErrors: Record<string, string> = {};
    const trimmedId = plantId.trim();
    if (!trimmedId) {
      clientErrors["plant_id"] = "Plant ID is required";
    } else if (!/^[a-z0-9_]{3,64}$/.test(trimmedId)) {
      clientErrors["plant_id"] =
        "Plant ID must be 3-64 chars: lowercase letters, numbers, underscores";
    }

    if (!name.trim()) {
      clientErrors["name"] = "Plant Name is required";
    }

    // Validate areas
    areas.forEach((area, aIdx) => {
      if (!area.area_code.trim()) {
        clientErrors[`areas.${aIdx}.area_code`] = "Area Code is required";
      }
      area.machines.forEach((mach, mIdx) => {
        if (!mach.machine_code.trim()) {
          clientErrors[`areas.${aIdx}.machines.${mIdx}.machine_code`] =
            "Machine Code is required";
        }
        mach.signals.forEach((sig, sIdx) => {
          if (!sig.signal_code.trim()) {
            clientErrors[`areas.${aIdx}.machines.${mIdx}.signals.${sIdx}.signal_code`] =
              "Signal Code is required";
          }
        });
      });
    });

    if (Object.keys(clientErrors).length > 0) {
      setFieldErrors(clientErrors);
      setGeneralError("Please fix highlighted errors before submitting.");
      return;
    }

    setIsSubmitting(true);

    const payload: Record<string, unknown> = {
      plant_id: trimmedId,
      name: name.trim(),
      timezone: timezone.trim() || "UTC",
      ...(isSelfService ? {} : viewerToken.trim() ? { viewer_token: viewerToken.trim() } : {}),
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
      const res = await onSubmit(payload);
      onSuccess(res);
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

  return (
    <div className="flex flex-col gap-6">
      {generalError && (
        <div
          role="alert"
          className="p-4 rounded-2xl bg-rose-50 border border-rose-300 text-rose-900 text-xs flex items-center gap-3 font-medium"
        >
          <span className="text-rose-600 font-bold text-base">✕</span>
          <span>{generalError}</span>
        </div>
      )}

      {/* JSON Definition Import Section */}
      <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-xs flex flex-col gap-5">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <div className="flex items-center gap-2">
            <span className="text-base">📋</span>
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-700">
              Import from Plant JSON Definition
            </h2>
          </div>
          <span className="text-[11px] text-slate-400 font-medium">Optional Shortcut</span>
        </div>

        <p className="text-xs text-slate-500 leading-relaxed">
          Quickly populate the creation form by pasting a raw plant JSON file or uploading one. The
          JSON is validated with advisory warnings before being applied to the fields below.
        </p>

        {/* File Upload Button */}
        <div className="flex items-center gap-3">
          <label
            htmlFor="json-file-input"
            className="text-xs font-semibold text-slate-700 shrink-0"
          >
            Upload JSON File:
          </label>
          <input
            id="json-file-input"
            type="file"
            accept=".json,application/json"
            onChange={handleFileUpload}
            className="text-xs text-slate-600 file:mr-3 file:py-1.5 file:px-3 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer"
          />
        </div>

        {/* Paste Area */}
        <div className="flex flex-col gap-2">
          <label htmlFor="json-paste-box" className="text-xs font-semibold text-slate-700">
            Or Paste JSON Definition:
          </label>
          <textarea
            id="json-paste-box"
            rows={5}
            value={jsonInputText}
            onChange={(e) => setJsonInputText(e.target.value)}
            placeholder={'{\n  "plant_id": "plant_example",\n  "name": "Example Plant",\n  "timezone": "UTC",\n  "areas": [...]\n}'}
            className="w-full px-4 py-2.5 rounded-xl border border-slate-300 font-mono text-xs text-slate-900 bg-slate-50 focus:bg-white focus:outline-hidden focus:ring-2 focus:ring-blue-500 transition-colors"
          />
          <div className="flex items-center gap-3 pt-1">
            <button
              type="button"
              onClick={() => applyJsonContent(jsonInputText)}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold shadow-xs transition-colors cursor-pointer"
            >
              Parse &amp; Fill Form
            </button>
            {jsonInputText && (
              <button
                type="button"
                onClick={() => {
                  setJsonInputText("");
                  setJsonSyntaxError(null);
                  setImportStatusMessage(null);
                  setAdvisoryErrors({});
                  setAdvisoryWarnings([]);
                }}
                className="px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold transition-colors cursor-pointer"
              >
                Clear Box
              </button>
            )}
          </div>
        </div>

        {/* Syntax Error Alert */}
        {jsonSyntaxError && (
          <div
            role="alert"
            className="p-4 rounded-2xl bg-rose-50 border border-rose-300 text-rose-900 text-xs flex flex-col gap-1 font-mono"
          >
            <div className="font-bold flex items-center gap-1.5 text-rose-700">
              <span>⚠️</span>
              <span>Syntax / Parse Error:</span>
            </div>
            <p className="whitespace-pre-wrap">{jsonSyntaxError}</p>
          </div>
        )}

        {/* Advisory Warnings / Errors */}
        {(Object.keys(advisoryErrors).length > 0 || advisoryWarnings.length > 0) && (
          <div
            role="alert"
            className="p-4 rounded-2xl bg-amber-50 border border-amber-300 text-amber-900 text-xs flex flex-col gap-1.5"
          >
            <div className="font-bold flex items-center gap-1.5 text-amber-800">
              <span>⚠️</span>
              <span>Advisory Validation Notice:</span>
            </div>
            <ul className="list-disc list-inside space-y-0.5 font-mono text-[11px]">
              {Object.entries(advisoryErrors).map(([field, msg]) => (
                <li key={`err-${field}`}>
                  <strong className="text-rose-950 font-bold">Error ({field}):</strong> {msg}
                </li>
              ))}
              {advisoryWarnings.map((warn, wIdx) => (
                <li key={`warn-${wIdx}`}>
                  <strong className="text-amber-950 font-bold">Warning:</strong> {warn}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Import Success Notification */}
        {importStatusMessage && !jsonSyntaxError && (
          <div className="p-4 rounded-2xl bg-emerald-50 border border-emerald-300 text-emerald-900 text-xs flex items-center gap-2 font-medium">
            <span className="text-emerald-600 text-base">✓</span>
            <span>{importStatusMessage}</span>
          </div>
        )}
      </div>

      {/* Main Creation Form */}
      <form onSubmit={handleSubmit} className="flex flex-col gap-8">
        {/* Plant Metadata */}
        <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-xs flex flex-col gap-6">
          <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400 border-b border-slate-100 pb-3">
            Plant Metadata &amp; Access
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

            {!isSelfService && (
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
            )}
          </div>
        </div>

        {/* Areas, Machines, Signals */}
        <div className="flex flex-col gap-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400">
              Plant Topology &amp; Signals ({areas.length} Areas)
            </h2>
            <button
              type="button"
              onClick={handleAddArea}
              className="px-3.5 py-1.5 rounded-xl bg-blue-50 hover:bg-blue-100 text-blue-700 text-xs font-bold border border-blue-200 transition-colors flex items-center gap-1.5 cursor-pointer"
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
                    className="text-xs text-rose-600 hover:text-rose-800 font-semibold px-2.5 py-1 rounded-lg hover:bg-rose-50 transition-colors cursor-pointer"
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
                    className="text-xs font-bold text-blue-600 hover:text-blue-800 cursor-pointer"
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
                          className="text-[11px] text-rose-600 hover:text-rose-800 font-medium cursor-pointer"
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
                          className="text-[11px] font-bold text-blue-600 hover:text-blue-800 cursor-pointer"
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
                                className="text-[10px] text-rose-600 hover:text-rose-800 cursor-pointer"
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
                                placeholder="e.g. temp_c"
                                className={`w-full px-2.5 py-1 rounded-md border font-mono text-xs text-slate-900 ${
                                  fieldErrors[
                                    `areas.${aIdx}.machines.${mIdx}.signals.${sIdx}.signal_code`
                                  ]
                                    ? "border-rose-400 bg-rose-50"
                                    : "border-slate-300"
                                }`}
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
                                className="w-full px-2.5 py-1 rounded-md border border-slate-300 text-xs text-slate-900"
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
                                placeholder="°C, bar, rpm"
                                className="w-full px-2.5 py-1 rounded-md border border-slate-300 text-xs text-slate-900"
                              />
                            </div>

                            <div className="flex flex-col gap-0.5">
                              <label className="text-[10px] text-slate-500">Data Type</label>
                              <select
                                value={sig.data_type}
                                onChange={(e) => {
                                  const next = [...areas];
                                  next[aIdx].machines[mIdx].signals[sIdx].data_type = e.target
                                    .value as "float" | "int" | "bool" | "string";
                                  setAreas(next);
                                }}
                                className="w-full px-2.5 py-1 rounded-md border border-slate-300 text-xs text-slate-900 bg-white"
                              >
                                <option value="float">float</option>
                                <option value="int">int</option>
                                <option value="bool">bool</option>
                                <option value="string">string</option>
                              </select>
                            </div>
                          </div>

                          {/* Signal Thresholds */}
                          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 pt-1 border-t border-slate-100">
                            <div>
                              <label className="text-[9px] text-slate-400 font-mono">normal_min</label>
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
                              <label className="text-[9px] text-slate-400 font-mono">normal_max</label>
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
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="px-5 py-2.5 rounded-xl text-xs font-bold text-slate-600 hover:text-slate-900 border border-slate-300 hover:bg-slate-50 transition-colors cursor-pointer"
            >
              Cancel
            </button>
          )}
          <button
            type="submit"
            disabled={isSubmitting}
            className="ml-auto px-6 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs font-bold transition-all shadow-xs flex items-center gap-2 cursor-pointer"
          >
            {isSubmitting ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                <span>Creating Facility...</span>
              </>
            ) : (
              <>
                <span>Create Plant &amp; Generate Credentials →</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
