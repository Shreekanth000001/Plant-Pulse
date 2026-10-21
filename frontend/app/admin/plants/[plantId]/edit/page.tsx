"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useAdminAuth } from "../../../layout";
import {
  fetchAdminPlantDetail,
  updateAdminPlant,
  diffPlantRemovals,
  parse409Removals,
  mapFastApi422Errors,
  formatAdminErrorMessage,
  AdminApiError,
  type AdminPlantDetail,
  type FastApiValidationErrorDetail,
} from "../../../../../lib/admin-api";
import { AdminRemovalModal } from "../../../../../components/admin/AdminRemovalModal";

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

export default function EditPlantPage() {
  const params = useParams();
  const plantId = (params?.plantId as string) || "";
  const router = useRouter();
  const { adminToken, reportApiError } = useAdminAuth();

  const [loading, setLoading] = useState(true);
  const [originalPlant, setOriginalPlant] = useState<AdminPlantDetail | null>(null);

  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [viewerToken, setViewerToken] = useState("");
  const [areas, setAreas] = useState<FormArea[]>([]);

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // 409 Removal Confirmation Flow State
  const [showRemovalModal, setShowRemovalModal] = useState(false);
  const [removedAreas, setRemovedAreas] = useState<string[]>([]);
  const [removedMachines, setRemovedMachines] = useState<string[]>([]);
  const [removedSignals, setRemovedSignals] = useState<string[]>([]);
  const [pendingPayload, setPendingPayload] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!plantId) return;
    let active = true;

    fetchAdminPlantDetail(plantId, adminToken)
      .then((data) => {
        if (!active) return;
        setOriginalPlant(data);
        setName(data.name || "");
        setTimezone(data.timezone || "UTC");
        setViewerToken("");

        const formAreas: FormArea[] = (data.areas || []).map((area) => ({
          area_code: area.area_code,
          name: area.name,
          machines: (area.machines || []).map((mach) => ({
            machine_code: mach.machine_code,
            name: mach.name,
            machine_type: mach.machine_type || "standard",
            signals: (mach.signals || []).map((sig) => ({
              signal_code: sig.signal_code,
              name: sig.name,
              unit: sig.unit || "",
              data_type: (sig.data_type as "float" | "int" | "bool" | "string") || "float",
              normal_min:
                sig.normal_min !== null && sig.normal_min !== undefined ? String(sig.normal_min) : "",
              normal_max:
                sig.normal_max !== null && sig.normal_max !== undefined ? String(sig.normal_max) : "",
              warn_min:
                sig.warn_min !== null && sig.warn_min !== undefined ? String(sig.warn_min) : "",
              warn_max:
                sig.warn_max !== null && sig.warn_max !== undefined ? String(sig.warn_max) : "",
              alarm_min:
                sig.alarm_min !== null && sig.alarm_min !== undefined ? String(sig.alarm_min) : "",
              alarm_max:
                sig.alarm_max !== null && sig.alarm_max !== undefined ? String(sig.alarm_max) : "",
            })),
          })),
        }));

        setAreas(formAreas);
        setLoading(false);
      })
      .catch((err) => {
        if (!active) return;
        setGeneralError(formatAdminErrorMessage(err));
        setLoading(false);
        reportApiError(err);
      });

    return () => {
      active = false;
    };
  }, [plantId, adminToken, reportApiError]);

  const handleAddArea = () => {
    const nextIdx = areas.length + 1;
    setAreas([
      ...areas,
      {
        area_code: `area_${nextIdx}`,
        name: `Area ${nextIdx}`,
        machines: [
          {
            machine_code: `mach_${nextIdx}_1`,
            name: `Machine 1`,
            machine_type: "standard",
            signals: [
              {
                signal_code: "temperature",
                name: "Temperature",
                unit: "°C",
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

  const buildPutPayload = (): Record<string, unknown> => {
    const payload: Record<string, unknown> = {
      plant_id: plantId.trim(),
      name: name.trim(),
      timezone: timezone.trim() || "UTC",
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

    // If viewerToken was filled, pass it to update hash; otherwise omit to keep existing hash
    if (viewerToken.trim().length > 0) {
      payload.viewer_token = viewerToken.trim();
    }

    return payload;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setGeneralError(null);
    setFieldErrors({});
    setIsSubmitting(true);

    const payload = buildPutPayload();

    try {
      await updateAdminPlant(adminToken, plantId, payload, false);
      router.push(`/admin/plants/${encodeURIComponent(plantId)}`);
    } catch (err: unknown) {
      if (err instanceof AdminApiError) {
        if (err.status === 409) {
          // Component removal conflict: calculate removals and open modal
          const parsed = parse409Removals(err.message);
          let remAreas = parsed.removedAreas;
          let remMachines = parsed.removedMachines;
          let remSignals = parsed.removedSignals;

          if (originalPlant) {
            const diff = diffPlantRemovals(originalPlant, payload as unknown as AdminPlantDetail);
            if (remAreas.length === 0) remAreas = diff.removedAreas;
            if (remMachines.length === 0) remMachines = diff.removedMachines;
            if (remSignals.length === 0) remSignals = diff.removedSignals;
          }

          setRemovedAreas(remAreas);
          setRemovedMachines(remMachines);
          setRemovedSignals(remSignals);
          setPendingPayload(payload);
          setShowRemovalModal(true);
        } else if (err.status === 422) {
          const validationDetails = (
            err as unknown as { validationErrors?: FastApiValidationErrorDetail[] }
          ).validationErrors;
          if (validationDetails) {
            const mapped = mapFastApi422Errors(validationDetails);
            setFieldErrors(mapped);
            setGeneralError("Validation failed. Please correct the highlighted fields below.");
          } else {
            setGeneralError(formatAdminErrorMessage(err));
          }
        } else {
          setGeneralError(formatAdminErrorMessage(err));
          reportApiError(err);
        }
      } else {
        setGeneralError("Failed to update plant definition. Verify server state.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConfirmRemovals = async () => {
    if (!pendingPayload) return;
    setIsSubmitting(true);
    setGeneralError(null);
    try {
      await updateAdminPlant(adminToken, plantId, pendingPayload, true);
      setShowRemovalModal(false);
      router.push(`/admin/plants/${encodeURIComponent(plantId)}`);
    } catch (err: unknown) {
      setShowRemovalModal(false);
      setGeneralError(formatAdminErrorMessage(err));
      reportApiError(err);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-white rounded-3xl p-8 border border-slate-200 animate-pulse flex flex-col gap-6 w-full">
        <div className="h-6 w-64 bg-slate-200 rounded" />
        <div className="h-4 w-96 bg-slate-100 rounded" />
        <div className="h-64 bg-slate-50 rounded-2xl border border-slate-100" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 w-full pb-16">
      {/* 409 Removal Confirmation Modal */}
      <AdminRemovalModal
        isOpen={showRemovalModal}
        isSubmitting={isSubmitting}
        removedAreas={removedAreas}
        removedMachines={removedMachines}
        removedSignals={removedSignals}
        onConfirm={handleConfirmRemovals}
        onCancel={() => setShowRemovalModal(false)}
      />

      {/* Breadcrumb Navigation */}
      <div className="flex items-center justify-between gap-4">
        <Link
          href={`/admin/plants/${encodeURIComponent(plantId)}`}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 hover:text-slate-900 transition-colors"
        >
          <span>&larr;</span>
          <span>Back to Plant Detail</span>
        </Link>
      </div>

      {/* Header Banner */}
      <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-2xs flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <span className="w-9 h-9 rounded-xl bg-amber-100 text-amber-800 flex items-center justify-center text-lg font-bold">
            ✏️
          </span>
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">
              Edit Plant: {name || plantId}
            </h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Modify topology, names, and signal alarm/warning boundaries for facility <code className="font-mono text-slate-800">{plantId}</code>.
            </p>
          </div>
        </div>
      </div>

      {/* General Error Banner */}
      {generalError && (
        <div
          role="alert"
          className="p-4 rounded-2xl bg-rose-50 border border-rose-200 text-rose-900 text-xs flex items-center gap-2.5 font-medium"
        >
          <span className="text-rose-600 font-bold text-base">✕</span>
          <span>{generalError}</span>
        </div>
      )}

      {/* Edit Form */}
      <form onSubmit={handleSubmit} className="flex flex-col gap-6">
        {/* Core Metadata Card */}
        <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-2xs flex flex-col gap-5">
          <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider text-2xs">
            1. Plant Identification &amp; Security
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Plant ID (Read-only on edit) */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="plant-id-input" className="text-xs font-semibold text-slate-700">
                Plant Identifier
              </label>
              <input
                id="plant-id-input"
                type="text"
                disabled
                value={plantId}
                className="px-3.5 py-2 text-xs font-mono rounded-xl border border-slate-200 bg-slate-100 text-slate-500 cursor-not-allowed"
              />
              <span className="text-2xs text-slate-400">
                Plant ID is immutable once registered.
              </span>
            </div>

            {/* Display Name */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="plant-name-input" className="text-xs font-semibold text-slate-700">
                Display Name <span className="text-rose-500">*</span>
              </label>
              <input
                id="plant-name-input"
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Acme Chemical Plant"
                className={`px-3.5 py-2 text-xs rounded-xl border ${
                  fieldErrors["name"] ? "border-rose-400 bg-rose-50/30" : "border-slate-300"
                } focus:outline-hidden focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all`}
              />
              {fieldErrors["name"] && (
                <span className="text-2xs text-rose-600 font-semibold">{fieldErrors["name"]}</span>
              )}
            </div>

            {/* Timezone */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="plant-tz-input" className="text-xs font-semibold text-slate-700">
                Timezone
              </label>
              <input
                id="plant-tz-input"
                type="text"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                placeholder="UTC, America/New_York, etc."
                className={`px-3.5 py-2 text-xs font-mono rounded-xl border ${
                  fieldErrors["timezone"] ? "border-rose-400 bg-rose-50/30" : "border-slate-300"
                } focus:outline-hidden focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all`}
              />
              {fieldErrors["timezone"] && (
                <span className="text-2xs text-rose-600 font-semibold">{fieldErrors["timezone"]}</span>
              )}
            </div>

            {/* Viewer Token (Blank preserves old) */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="plant-token-input" className="text-xs font-semibold text-slate-700">
                Update Viewer Token (Optional)
              </label>
              <input
                id="plant-token-input"
                type="password"
                value={viewerToken}
                onChange={(e) => setViewerToken(e.target.value)}
                placeholder="Leave blank to keep existing viewer token"
                className={`px-3.5 py-2 text-xs font-mono rounded-xl border ${
                  fieldErrors["viewer_token"] ? "border-rose-400 bg-rose-50/30" : "border-slate-300"
                } focus:outline-hidden focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all`}
              />
              <span className="text-2xs text-slate-500">
                Leave blank to keep current token. (Viewer token removal is not supported).
              </span>
              {fieldErrors["viewer_token"] && (
                <span className="text-2xs text-rose-600 font-semibold">{fieldErrors["viewer_token"]}</span>
              )}
            </div>
          </div>
        </div>

        {/* Dynamic Topology Hierarchy */}
        <div className="flex flex-col gap-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider text-2xs">
                2. Production Areas &amp; Machine Topology
              </h2>
              <p className="text-2xs text-slate-500">
                Configure areas, machines, and metric signals.
              </p>
            </div>
            <button
              type="button"
              onClick={handleAddArea}
              className="px-3 py-1.5 text-xs font-bold text-blue-700 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-xl transition-all cursor-pointer flex items-center gap-1.5"
            >
              <span>+</span>
              <span>Add Area</span>
            </button>
          </div>

          {areas.map((area, aIdx) => (
            <div
              key={aIdx}
              className="bg-white rounded-3xl border border-slate-200 shadow-2xs overflow-hidden flex flex-col"
            >
              {/* Area Header Bar */}
              <div className="bg-slate-50/80 px-6 py-4 border-b border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <span className="w-7 h-7 rounded-lg bg-blue-100 text-blue-800 flex items-center justify-center text-xs font-bold font-mono">
                    A{aIdx + 1}
                  </span>
                  <div className="flex flex-wrap items-center gap-3">
                    <input
                      type="text"
                      required
                      value={area.area_code}
                      onChange={(e) => {
                        const next = [...areas];
                        next[aIdx].area_code = e.target.value;
                        setAreas(next);
                      }}
                      placeholder="area_code"
                      className={`px-2.5 py-1 text-xs font-mono font-bold rounded-lg border ${
                        fieldErrors[`areas.${aIdx}.area_code`]
                          ? "border-rose-400 bg-rose-50"
                          : "border-slate-300"
                      } bg-white`}
                    />
                    <input
                      type="text"
                      required
                      value={area.name}
                      onChange={(e) => {
                        const next = [...areas];
                        next[aIdx].name = e.target.value;
                        setAreas(next);
                      }}
                      placeholder="Area Name"
                      className={`px-2.5 py-1 text-xs font-semibold rounded-lg border ${
                        fieldErrors[`areas.${aIdx}.name`]
                          ? "border-rose-400 bg-rose-50"
                          : "border-slate-300"
                      } bg-white`}
                    />
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleAddMachine(aIdx)}
                    className="px-2.5 py-1 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg transition-colors cursor-pointer"
                  >
                    + Machine
                  </button>
                  {areas.length > 1 && (
                    <button
                      type="button"
                      onClick={() => handleRemoveArea(aIdx)}
                      className="px-2.5 py-1 text-xs font-semibold text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-lg transition-colors cursor-pointer"
                    >
                      Delete Area
                    </button>
                  )}
                </div>
              </div>

              {/* Machines inside this Area */}
              <div className="p-6 flex flex-col gap-6">
                {area.machines.map((mach, mIdx) => (
                  <div
                    key={mIdx}
                    className="bg-slate-50/50 rounded-2xl border border-slate-200 p-5 flex flex-col gap-4"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200/80">
                      <div className="flex items-center gap-2.5">
                        <span className="w-6 h-6 rounded-md bg-slate-200 text-slate-700 flex items-center justify-center text-xs font-bold font-mono">
                          M{mIdx + 1}
                        </span>
                        <input
                          type="text"
                          required
                          value={mach.machine_code}
                          onChange={(e) => {
                            const next = [...areas];
                            next[aIdx].machines[mIdx].machine_code = e.target.value;
                            setAreas(next);
                          }}
                          placeholder="machine_code"
                          className="px-2.5 py-1 text-xs font-mono font-bold rounded-lg border border-slate-300 bg-white"
                        />
                        <input
                          type="text"
                          required
                          value={mach.name}
                          onChange={(e) => {
                            const next = [...areas];
                            next[aIdx].machines[mIdx].name = e.target.value;
                            setAreas(next);
                          }}
                          placeholder="Machine Name"
                          className="px-2.5 py-1 text-xs font-semibold rounded-lg border border-slate-300 bg-white"
                        />
                      </div>

                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleAddSignal(aIdx, mIdx)}
                          className="px-2 py-1 text-2xs font-semibold text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-md cursor-pointer"
                        >
                          + Signal
                        </button>
                        {area.machines.length > 1 && (
                          <button
                            type="button"
                            onClick={() => handleRemoveMachine(aIdx, mIdx)}
                            className="px-2 py-1 text-2xs font-semibold text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-md cursor-pointer"
                          >
                            Delete Machine
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Signals Table */}
                    <div className="overflow-x-auto">
                      <table className="w-full text-left border-collapse text-2xs">
                        <thead>
                          <tr className="border-b border-slate-200 text-slate-500 font-semibold uppercase tracking-wider">
                            <th className="py-1 px-1">Signal Code</th>
                            <th className="py-1 px-1">Name</th>
                            <th className="py-1 px-1">Unit</th>
                            <th className="py-1 px-1">Type</th>
                            <th className="py-1 px-1">Normal Range</th>
                            <th className="py-1 px-1">Warn Range</th>
                            <th className="py-1 px-1">Alarm Range</th>
                            <th className="py-1 px-1 text-right">Action</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 font-mono">
                          {mach.signals.map((sig, sIdx) => (
                            <tr key={sIdx} className="hover:bg-white/60">
                              <td className="py-1.5 px-1">
                                <input
                                  type="text"
                                  required
                                  value={sig.signal_code}
                                  onChange={(e) => {
                                    const next = [...areas];
                                    next[aIdx].machines[mIdx].signals[sIdx].signal_code =
                                      e.target.value;
                                    setAreas(next);
                                  }}
                                  placeholder="temp"
                                  className="w-20 px-1.5 py-0.5 text-2xs border border-slate-300 rounded bg-white"
                                />
                              </td>
                              <td className="py-1.5 px-1 font-sans">
                                <input
                                  type="text"
                                  required
                                  value={sig.name}
                                  onChange={(e) => {
                                    const next = [...areas];
                                    next[aIdx].machines[mIdx].signals[sIdx].name = e.target.value;
                                    setAreas(next);
                                  }}
                                  placeholder="Temperature"
                                  className="w-28 px-1.5 py-0.5 text-2xs border border-slate-300 rounded bg-white"
                                />
                              </td>
                              <td className="py-1.5 px-1">
                                <input
                                  type="text"
                                  value={sig.unit}
                                  onChange={(e) => {
                                    const next = [...areas];
                                    next[aIdx].machines[mIdx].signals[sIdx].unit = e.target.value;
                                    setAreas(next);
                                  }}
                                  placeholder="°C"
                                  className="w-12 px-1.5 py-0.5 text-2xs border border-slate-300 rounded bg-white"
                                />
                              </td>
                              <td className="py-1.5 px-1">
                                <select
                                  value={sig.data_type}
                                  onChange={(e) => {
                                    const next = [...areas];
                                    next[aIdx].machines[mIdx].signals[sIdx].data_type = e.target
                                      .value as "float" | "int" | "bool" | "string";
                                    setAreas(next);
                                  }}
                                  className="px-1 py-0.5 text-2xs border border-slate-300 rounded bg-white"
                                >
                                  <option value="float">float</option>
                                  <option value="int">int</option>
                                  <option value="bool">bool</option>
                                  <option value="string">string</option>
                                </select>
                              </td>
                              <td className="py-1.5 px-1">
                                <div className="flex items-center gap-1">
                                  <input
                                    type="text"
                                    value={sig.normal_min}
                                    onChange={(e) => {
                                      const next = [...areas];
                                      next[aIdx].machines[mIdx].signals[sIdx].normal_min =
                                        e.target.value;
                                      setAreas(next);
                                    }}
                                    placeholder="min"
                                    className="w-10 px-1 py-0.5 text-2xs border border-slate-200 rounded bg-white"
                                  />
                                  <span>-</span>
                                  <input
                                    type="text"
                                    value={sig.normal_max}
                                    onChange={(e) => {
                                      const next = [...areas];
                                      next[aIdx].machines[mIdx].signals[sIdx].normal_max =
                                        e.target.value;
                                      setAreas(next);
                                    }}
                                    placeholder="max"
                                    className="w-10 px-1 py-0.5 text-2xs border border-slate-200 rounded bg-white"
                                  />
                                </div>
                              </td>
                              <td className="py-1.5 px-1">
                                <div className="flex items-center gap-1">
                                  <input
                                    type="text"
                                    value={sig.warn_min}
                                    onChange={(e) => {
                                      const next = [...areas];
                                      next[aIdx].machines[mIdx].signals[sIdx].warn_min =
                                        e.target.value;
                                      setAreas(next);
                                    }}
                                    placeholder="min"
                                    className="w-10 px-1 py-0.5 text-2xs border border-amber-200 rounded bg-amber-50/40"
                                  />
                                  <span>-</span>
                                  <input
                                    type="text"
                                    value={sig.warn_max}
                                    onChange={(e) => {
                                      const next = [...areas];
                                      next[aIdx].machines[mIdx].signals[sIdx].warn_max =
                                        e.target.value;
                                      setAreas(next);
                                    }}
                                    placeholder="max"
                                    className="w-10 px-1 py-0.5 text-2xs border border-amber-200 rounded bg-amber-50/40"
                                  />
                                </div>
                              </td>
                              <td className="py-1.5 px-1">
                                <div className="flex items-center gap-1">
                                  <input
                                    type="text"
                                    value={sig.alarm_min}
                                    onChange={(e) => {
                                      const next = [...areas];
                                      next[aIdx].machines[mIdx].signals[sIdx].alarm_min =
                                        e.target.value;
                                      setAreas(next);
                                    }}
                                    placeholder="min"
                                    className="w-10 px-1 py-0.5 text-2xs border border-rose-200 rounded bg-rose-50/40"
                                  />
                                  <span>-</span>
                                  <input
                                    type="text"
                                    value={sig.alarm_max}
                                    onChange={(e) => {
                                      const next = [...areas];
                                      next[aIdx].machines[mIdx].signals[sIdx].alarm_max =
                                        e.target.value;
                                      setAreas(next);
                                    }}
                                    placeholder="max"
                                    className="w-10 px-1 py-0.5 text-2xs border border-rose-200 rounded bg-rose-50/40"
                                  />
                                </div>
                              </td>
                              <td className="py-1.5 px-1 text-right">
                                {mach.signals.length > 1 && (
                                  <button
                                    type="button"
                                    onClick={() => handleRemoveSignal(aIdx, mIdx, sIdx)}
                                    className="text-slate-400 hover:text-rose-600 px-1"
                                    title="Remove signal"
                                  >
                                    ✕
                                  </button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Submit Button Bar */}
        <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200">
          <Link
            href={`/admin/plants/${encodeURIComponent(plantId)}`}
            className="px-5 py-2.5 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50 border border-slate-300 rounded-xl transition-all cursor-pointer"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={isSubmitting}
            className="px-6 py-2.5 text-xs font-bold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-xl transition-all shadow-sm hover:shadow cursor-pointer flex items-center gap-2"
          >
            {isSubmitting ? (
              <>
                <span className="animate-spin">🔄</span>
                <span>Saving Changes...</span>
              </>
            ) : (
              <span>Save Plant Definition</span>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
