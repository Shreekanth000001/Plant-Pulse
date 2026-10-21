"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useAdminAuth } from "../../layout";
import {
  fetchAdminPlantDetail,
  formatAdminErrorMessage,
  type AdminPlantDetail,
} from "../../../../lib/admin-api";

export default function AdminPlantDetailPage() {
  const params = useParams();
  const plantId = (params?.plantId as string) || "";
  const { adminToken, reportApiError } = useAdminAuth();

  const [plant, setPlant] = useState<AdminPlantDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    if (!plantId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAdminPlantDetail(plantId, adminToken);
      setPlant(data);
    } catch (err) {
      const msg = formatAdminErrorMessage(err);
      setError(msg);
      reportApiError(err);
    } finally {
      setLoading(false);
    }
  }, [plantId, adminToken, reportApiError]);

  useEffect(() => {
    if (!plantId) return;
    let active = true;
    fetchAdminPlantDetail(plantId, adminToken)
      .then((data) => {
        if (!active) return;
        setPlant(data);
        setLoading(false);
      })
      .catch((err) => {
        if (!active) return;
        const msg = formatAdminErrorMessage(err);
        setError(msg);
        setLoading(false);
        reportApiError(err);
      });

    return () => {
      active = false;
    };
  }, [plantId, adminToken, reportApiError]);

  const totalMachines =
    plant?.areas.reduce((acc, a) => acc + (a.machines ? a.machines.length : 0), 0) ?? 0;
  const totalSignals =
    plant?.areas.reduce(
      (acc, a) =>
        acc +
        (a.machines
          ? a.machines.reduce((mAcc, m) => mAcc + (m.signals ? m.signals.length : 0), 0)
          : 0),
      0
    ) ?? 0;

  return (
    <div className="flex flex-col gap-6 w-full pb-12">
      {/* Breadcrumb & Navigation */}
      <div className="flex items-center justify-between gap-4">
        <Link
          href="/admin"
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 hover:text-slate-900 transition-colors"
        >
          <span>&larr;</span>
          <span>Back to All Plants</span>
        </Link>
        <button
          type="button"
          onClick={loadDetail}
          disabled={loading}
          className="px-3.5 py-1.5 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50 border border-slate-300 rounded-xl transition-all shadow-2xs cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
        >
          <span className={loading ? "animate-spin" : ""}>🔄</span>
          <span>Refresh</span>
        </button>
      </div>

      {/* Error View */}
      {error && (
        <div
          role="alert"
          className="p-5 rounded-2xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex flex-col gap-3 font-medium"
        >
          <div className="flex items-center gap-2">
            <span className="text-rose-600 font-bold text-base">✕</span>
            <span className="font-semibold text-sm">Failed to Load Plant Detail</span>
          </div>
          <p>{error}</p>
          <div className="pt-2">
            <button
              type="button"
              onClick={loadDetail}
              className="px-4 py-1.5 bg-white hover:bg-rose-100 text-rose-900 border border-rose-300 rounded-lg text-xs font-semibold transition-all cursor-pointer"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {/* Loading Skeleton */}
      {loading && (
        <div className="bg-white rounded-3xl p-8 border border-slate-200 animate-pulse flex flex-col gap-6">
          <div className="h-6 w-64 bg-slate-200 rounded" />
          <div className="h-4 w-96 bg-slate-100 rounded" />
          <div className="grid grid-cols-3 gap-4 pt-4">
            <div className="h-20 bg-slate-100 rounded-2xl" />
            <div className="h-20 bg-slate-100 rounded-2xl" />
            <div className="h-20 bg-slate-100 rounded-2xl" />
          </div>
        </div>
      )}

      {/* Detail Content */}
      {!loading && plant && (
        <>
          {/* Header Card */}
          <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-2xs flex flex-col gap-5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-3">
                  <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">
                    {plant.name}
                  </h1>
                  <span className="px-3 py-1 rounded-lg bg-slate-100 border border-slate-200 text-xs font-mono font-semibold text-slate-800">
                    {plant.plant_id}
                  </span>
                </div>
                <p className="text-xs text-slate-500 mt-1 flex items-center gap-3">
                  <span>Timezone: <strong className="text-slate-700 font-mono">{plant.timezone || "UTC"}</strong></span>
                  <span>•</span>
                  <span>
                    Status:{" "}
                    {plant.has_viewer_token ? (
                      <span className="text-amber-700 font-semibold">Protected (Viewer Token Required)</span>
                    ) : (
                      <span className="text-emerald-700 font-semibold">Public (No Token)</span>
                    )}
                  </span>
                </p>
              </div>

              <div className="flex items-center gap-2">
                <span className="px-3 py-1.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-700 text-xs font-mono font-medium">
                  {plant.areas.length} Areas • {totalMachines} Machines • {totalSignals} Signals
                </span>
              </div>
            </div>

            {/* Device Usernames */}
            <div className="pt-4 border-t border-slate-100 flex flex-col gap-2">
              <span className="text-2xs uppercase tracking-wider font-semibold text-slate-400">
                Registered Device Credentials
              </span>
              <div className="flex flex-wrap items-center gap-2">
                {plant.device_usernames && plant.device_usernames.length > 0 ? (
                  plant.device_usernames.map((u) => (
                    <span
                      key={u}
                      className="px-3 py-1 rounded-xl bg-slate-100 border border-slate-200 text-xs font-mono text-slate-800 flex items-center gap-1.5"
                    >
                      <span>🔑</span>
                      <span>{u}</span>
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-slate-400 italic">
                    No device credentials registered yet.
                  </span>
                )}
                <span className="text-2xs text-slate-400 ml-2">
                  (Passwords and password hashes are redacted by the detail API)
                </span>
              </div>
            </div>
          </div>

          {/* Areas, Machines & Signals Hierarchy */}
          <div className="flex flex-col gap-6">
            <h2 className="text-base font-bold text-slate-900 tracking-tight flex items-center gap-2">
              <span>📐</span>
              <span>Plant Layout &amp; Signal Definitions</span>
            </h2>

            {plant.areas.length === 0 ? (
              <div className="bg-white rounded-2xl p-8 border border-slate-200 text-center text-xs text-slate-500">
                No areas or machines defined for this plant.
              </div>
            ) : (
              plant.areas.map((area) => (
                <div
                  key={area.area_code}
                  className="bg-white rounded-3xl border border-slate-200 shadow-2xs overflow-hidden"
                >
                  {/* Area Header */}
                  <div className="bg-slate-50/80 px-6 py-4 border-b border-slate-200 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="w-7 h-7 rounded-lg bg-blue-100 text-blue-800 flex items-center justify-center text-xs font-bold font-mono">
                        A
                      </span>
                      <div>
                        <h3 className="text-sm font-bold text-slate-900">{area.name}</h3>
                        <span className="text-2xs font-mono text-slate-500">
                          area_code: {area.area_code} (order: {area.display_order ?? 0})
                        </span>
                      </div>
                    </div>
                    <span className="text-xs text-slate-500 font-mono">
                      {area.machines.length} machine{area.machines.length === 1 ? "" : "s"}
                    </span>
                  </div>

                  {/* Machines in Area */}
                  <div className="p-6 flex flex-col gap-6">
                    {area.machines.map((machine) => (
                      <div
                        key={machine.machine_code}
                        className="bg-slate-50/40 rounded-2xl border border-slate-200/80 p-5 flex flex-col gap-4"
                      >
                        {/* Machine Header */}
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-200/60">
                          <div className="flex items-center gap-2.5">
                            <span className="w-6 h-6 rounded-md bg-slate-200 text-slate-700 flex items-center justify-center text-xs font-bold font-mono">
                              M
                            </span>
                            <div>
                              <h4 className="text-xs font-bold text-slate-900">
                                {machine.name}
                              </h4>
                              <span className="text-2xs font-mono text-slate-500">
                                machine_code: {machine.machine_code} • type:{" "}
                                {machine.machine_type || "standard"}
                              </span>
                            </div>
                          </div>
                          <span className="text-2xs text-slate-500 font-mono">
                            {machine.signals.length} signal{machine.signals.length === 1 ? "" : "s"}
                          </span>
                        </div>

                        {/* Signals Table */}
                        {machine.signals.length === 0 ? (
                          <div className="text-2xs text-slate-400 italic py-2">
                            No signals configured for this machine.
                          </div>
                        ) : (
                          <div className="overflow-x-auto">
                            <table className="w-full text-left border-collapse text-2xs">
                              <thead>
                                <tr className="border-b border-slate-200 text-slate-500 font-semibold uppercase tracking-wider">
                                  <th className="py-2 px-2">Signal Code</th>
                                  <th className="py-2 px-2">Signal Name</th>
                                  <th className="py-2 px-2">Unit</th>
                                  <th className="py-2 px-2">Data Type</th>
                                  <th className="py-2 px-2">Setpoint</th>
                                  <th className="py-2 px-2">Normal Range</th>
                                  <th className="py-2 px-2">Warn Range</th>
                                  <th className="py-2 px-2">Alarm Range</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-slate-100 font-mono text-slate-700">
                                {machine.signals.map((sig) => (
                                  <tr key={sig.signal_code} className="hover:bg-white/80">
                                    <td className="py-2.5 px-2 font-semibold text-slate-900">
                                      {sig.signal_code}
                                    </td>
                                    <td className="py-2.5 px-2 font-sans font-medium text-slate-800">
                                      {sig.name}
                                    </td>
                                    <td className="py-2.5 px-2 text-slate-500">
                                      {sig.unit || "—"}
                                    </td>
                                    <td className="py-2.5 px-2">
                                      <span className="px-1.5 py-0.5 rounded bg-slate-200/60 text-slate-700 text-3xs font-semibold uppercase">
                                        {sig.data_type}
                                      </span>
                                    </td>
                                    <td className="py-2.5 px-2">
                                      {sig.is_setpoint ? (
                                        <span className="text-blue-700 font-semibold">Yes</span>
                                      ) : sig.setpoint_signal_code ? (
                                        <span className="text-slate-500">
                                          &rarr; {sig.setpoint_signal_code}
                                        </span>
                                      ) : (
                                        <span className="text-slate-400">No</span>
                                      )}
                                    </td>
                                    <td className="py-2.5 px-2 text-slate-600">
                                      {sig.normal_min !== null && sig.normal_min !== undefined
                                        ? `[${sig.normal_min}, ${sig.normal_max ?? "∞"}]`
                                        : "—"}
                                    </td>
                                    <td className="py-2.5 px-2 text-amber-700">
                                      {sig.warn_min !== null && sig.warn_min !== undefined
                                        ? `[${sig.warn_min}, ${sig.warn_max ?? "∞"}]`
                                        : "—"}
                                    </td>
                                    <td className="py-2.5 px-2 text-rose-700">
                                      {sig.alarm_min !== null && sig.alarm_min !== undefined
                                        ? `[${sig.alarm_min}, ${sig.alarm_max ?? "∞"}]`
                                        : "—"}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
