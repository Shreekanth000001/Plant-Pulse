"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useAdminAuth } from "./layout";
import {
  fetchAdminPlants,
  formatAdminErrorMessage,
  type AdminPlantSummary,
} from "../../lib/admin-api";

export default function AdminPlantsPage() {
  const { adminToken, reportApiError } = useAdminAuth();
  const [plants, setPlants] = useState<AdminPlantSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadPlants = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAdminPlants(adminToken);
      setPlants(data);
    } catch (err) {
      const msg = formatAdminErrorMessage(err);
      setError(msg);
      reportApiError(err);
    } finally {
      setLoading(false);
    }
  }, [adminToken, reportApiError]);

  useEffect(() => {
    let active = true;
    fetchAdminPlants(adminToken)
      .then((data) => {
        if (!active) return;
        setPlants(data);
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
  }, [adminToken, reportApiError]);

  const protectedCount = plants.filter((p) => p.has_viewer_token).length;
  const publicCount = plants.length - protectedCount;

  return (
    <div className="flex flex-col gap-6 w-full">
      {/* Top Title Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2.5">
            <span>🏭</span>
            <span>Registered Plants</span>
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-700 font-mono font-semibold border border-slate-200">
              {plants.length} Total
            </span>
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Read-only configuration and architecture summary for all registered facilities.
          </p>
        </div>

        <button
          type="button"
          onClick={loadPlants}
          disabled={loading}
          className="px-4 py-2 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50 border border-slate-300 rounded-xl transition-all shadow-2xs cursor-pointer flex items-center gap-2 self-start sm:self-auto disabled:opacity-50"
        >
          <span className={loading ? "animate-spin" : ""}>🔄</span>
          <span>Refresh</span>
        </button>
      </div>

      {/* Stats Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white rounded-2xl p-4 border border-slate-200 shadow-2xs">
          <div className="text-2xs font-semibold text-slate-400 uppercase tracking-wider">
            Total Plants
          </div>
          <div className="text-2xl font-bold text-slate-900 mt-1 font-mono">
            {loading ? "..." : plants.length}
          </div>
          <div className="text-2xs text-slate-500 mt-0.5">Seeded and custom facilities</div>
        </div>

        <div className="bg-white rounded-2xl p-4 border border-slate-200 shadow-2xs">
          <div className="text-2xs font-semibold text-amber-600 uppercase tracking-wider">
            Protected Plants
          </div>
          <div className="text-2xl font-bold text-amber-700 mt-1 font-mono">
            {loading ? "..." : protectedCount}
          </div>
          <div className="text-2xs text-slate-500 mt-0.5">Require viewer access token</div>
        </div>

        <div className="bg-white rounded-2xl p-4 border border-slate-200 shadow-2xs">
          <div className="text-2xs font-semibold text-emerald-600 uppercase tracking-wider">
            Public Plants
          </div>
          <div className="text-2xl font-bold text-emerald-700 mt-1 font-mono">
            {loading ? "..." : publicCount}
          </div>
          <div className="text-2xs text-slate-500 mt-0.5">Open viewer access</div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div
          role="alert"
          className="p-4 rounded-2xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center justify-between gap-4 font-medium"
        >
          <div className="flex items-center gap-2.5">
            <span className="text-rose-600 font-bold text-base">✕</span>
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={loadPlants}
            className="px-3 py-1 bg-white hover:bg-rose-100 text-rose-800 border border-rose-300 rounded-lg text-xs font-semibold transition-all cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      {/* Loading Skeleton */}
      {loading && (
        <div className="bg-white rounded-2xl border border-slate-200 divide-y divide-slate-100 p-6 flex flex-col gap-4">
          {[1, 2].map((i) => (
            <div key={i} className="animate-pulse flex items-center justify-between py-3">
              <div className="flex flex-col gap-2">
                <div className="h-4 w-48 bg-slate-200 rounded" />
                <div className="h-3 w-32 bg-slate-100 rounded" />
              </div>
              <div className="h-8 w-24 bg-slate-200 rounded-xl" />
            </div>
          ))}
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && plants.length === 0 && (
        <div className="bg-white rounded-3xl p-12 border border-slate-200 text-center flex flex-col items-center gap-3">
          <span className="text-3xl">🌱</span>
          <h3 className="text-base font-bold text-slate-800">No Plants Registered</h3>
          <p className="text-xs text-slate-500 max-w-sm">
            No plants are currently registered in the database.
          </p>
        </div>
      )}

      {/* Plants Table / List */}
      {!loading && !error && plants.length > 0 && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-2xs overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50/80 border-b border-slate-200 text-2xs uppercase tracking-wider font-semibold text-slate-500">
                  <th className="py-3.5 px-4 sm:px-6">Plant ID</th>
                  <th className="py-3.5 px-4">Plant Name</th>
                  <th className="py-3.5 px-4">Timezone</th>
                  <th className="py-3.5 px-4">Viewer Token</th>
                  <th className="py-3.5 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs text-slate-700">
                {plants.map((plant) => (
                  <tr
                    key={plant.plant_id}
                    className="hover:bg-slate-50/60 transition-colors group"
                  >
                    <td className="py-4 px-4 sm:px-6 font-mono font-medium text-slate-900">
                      <span className="bg-slate-100 px-2.5 py-1 rounded-lg border border-slate-200">
                        {plant.plant_id}
                      </span>
                    </td>
                    <td className="py-4 px-4 font-semibold text-slate-900">
                      {plant.name}
                    </td>
                    <td className="py-4 px-4 text-slate-500 font-mono text-2xs">
                      {plant.timezone || "UTC"}
                    </td>
                    <td className="py-4 px-4">
                      {plant.has_viewer_token ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-200 font-medium text-2xs">
                          <span>🔒</span>
                          <span>Protected</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200 text-2xs">
                          <span>🌐</span>
                          <span>Public</span>
                        </span>
                      )}
                    </td>
                    <td className="py-4 px-4 text-right">
                      <Link
                        href={`/admin/plants/${encodeURIComponent(plant.plant_id)}`}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900 hover:bg-slate-800 active:bg-black text-white font-medium text-xs transition-all shadow-2xs"
                      >
                        <span>View Details</span>
                        <span aria-hidden="true">&rarr;</span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
