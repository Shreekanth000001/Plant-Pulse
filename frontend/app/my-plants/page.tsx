"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import {
  fetchMyPlants,
  fetchMyPlantDetail,
  createMyPlant,
  rotateMyPlantCredentials,
  rotateMyPlantViewerToken,
  deleteMyPlant,
  formatPlantQuota,
  canCreatePlant,
  buildTelemetryExampleJson,
  buildMosquittoPubCommand,
  type MyPlantSummary,
  type AdminPlantDetail,
  type OneTimeDeviceCredential,
} from "../../lib/me-api";
import { AdminCredentialsModal } from "../../components/admin/AdminCredentialsModal";
import { AdminDeleteModal } from "../../components/admin/AdminDeleteModal";
import { PlantCreateForm } from "../../components/admin/PlantCreateForm";
import { safeLocalStorageSet } from "../../lib/plant-utils";
import { useMounted } from "../../lib/useMounted";

export default function MyPlantsPage() {
  const router = useRouter();
  const { isLoaded, isSignedIn, getToken } = useAuth();

  const [plants, setPlants] = useState<MyPlantSummary[]>([]);
  const [selectedPlantId, setSelectedPlantId] = useState<string | null>(null);
  const [selectedPlantDetail, setSelectedPlantDetail] = useState<AdminPlantDetail | null>(null);
  const [isLoadingPlants, setIsLoadingPlants] = useState(true);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const mounted = useMounted();
  const [showCreateForm, setShowCreateForm] = useState(false);

  // Credential Modal State
  const [credModalOpen, setCredModalOpen] = useState(false);
  const [credModalSource, setCredModalSource] = useState<
    "create" | "rotate" | "viewer-token-rotate" | null
  >(null);
  const [modalCredentials, setModalCredentials] = useState<OneTimeDeviceCredential[] | null>(null);
  const [modalViewerToken, setModalViewerToken] = useState<string | null>(null);
  const [modalPlantId, setModalPlantId] = useState<string | null>(null);
  const [modalBrokerReloaded, setModalBrokerReloaded] = useState<boolean | undefined>(undefined);

  // Delete Modal State
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Clipboard feedback
  const [cmdCopied, setCmdCopied] = useState(false);
  const [jsonCopied, setJsonCopied] = useState(false);

  // 1. Authentication Guard: redirect to /sign-in if not signed in
  useEffect(() => {
    if (isLoaded && !isSignedIn) {
      router.push("/sign-in");
    }
  }, [isLoaded, isSignedIn, router]);

  // 2. Load caller's plants on mount
  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    let active = true;

    getToken().then((token) => {
      if (!active || !token) return;
      fetchMyPlants(token)
        .then((data) => {
          if (!active) return;
          setPlants(data);
          setIsLoadingPlants(false);
          setSelectedPlantId((prev) => {
            if (prev && data.some((p) => p.plant_id === prev)) return prev;
            return data.length > 0 ? data[0].plant_id : null;
          });
        })
        .catch((err) => {
          if (!active) return;
          setErrorMessage(
            err instanceof Error ? err.message : "Failed to load facilities"
          );
          setIsLoadingPlants(false);
        });
    });

    return () => {
      active = false;
    };
  }, [isLoaded, isSignedIn, getToken]);

  const refreshPlants = useCallback(
    async (selectIdAfterLoad?: string) => {
      if (!isSignedIn) return;
      setIsLoadingPlants(true);
      setErrorMessage(null);
      try {
        const token = await getToken();
        if (!token) return;
        const data = await fetchMyPlants(token);
        setPlants(data);
        if (selectIdAfterLoad) {
          setSelectedPlantId(selectIdAfterLoad);
        } else if (data.length > 0) {
          setSelectedPlantId((prev) =>
            prev && data.some((p) => p.plant_id === prev) ? prev : data[0].plant_id
          );
        } else {
          setSelectedPlantId(null);
          setSelectedPlantDetail(null);
        }
      } catch (err: unknown) {
        setErrorMessage(
          err instanceof Error ? err.message : "Failed to load facilities"
        );
      } finally {
        setIsLoadingPlants(false);
      }
    },
    [isSignedIn, getToken]
  );

  // 3. Load detail when selectedPlantId changes
  useEffect(() => {
    let active = true;
    if (!selectedPlantId || !isSignedIn) {
      return;
    }

    getToken().then((token) => {
      if (!active || !token) return;
      setIsLoadingDetail(true);
      fetchMyPlantDetail(selectedPlantId, token)
        .then((detail) => {
          if (!active) return;
          setSelectedPlantDetail(detail);
          setIsLoadingDetail(false);
        })
        .catch(() => {
          if (!active) return;
          setSelectedPlantDetail(null);
          setIsLoadingDetail(false);
        });
    });

    return () => {
      active = false;
    };
  }, [selectedPlantId, isSignedIn, getToken]);

  // Actions
  const handleOpenDashboard = (plantId: string) => {
    safeLocalStorageSet("plantpulse_active_plant", plantId);
    router.push("/");
  };

  const handleRotateCredentials = async () => {
    if (!selectedPlantId) return;
    try {
      const token = await getToken();
      if (!token) return;
      const res = await rotateMyPlantCredentials(selectedPlantId, token);
      setModalCredentials([
        {
          username: res.username,
          password: res.password,
          client_id: res.username,
        },
      ]);
      setModalViewerToken(null);
      setModalPlantId(selectedPlantId);
      setModalBrokerReloaded(res.broker_reloaded);
      setCredModalSource("rotate");
      setCredModalOpen(true);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to rotate credentials");
    }
  };

  const handleRotateViewerToken = async () => {
    if (!selectedPlantId) return;
    try {
      const token = await getToken();
      if (!token) return;
      const res = await rotateMyPlantViewerToken(selectedPlantId, token);
      setModalCredentials(null);
      setModalViewerToken(res.viewer_token);
      setModalPlantId(selectedPlantId);
      setModalBrokerReloaded(undefined);
      setCredModalSource("viewer-token-rotate");
      setCredModalOpen(true);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to rotate viewer token");
    }
  };

  const handleDeleteConfirm = async () => {
    if (!selectedPlantId) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      const token = await getToken();
      if (!token) return;
      await deleteMyPlant(selectedPlantId, token);
      setDeleteModalOpen(false);
      await refreshPlants();
    } catch (err: unknown) {
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete plant facility"
      );
    } finally {
      setIsDeleting(false);
    }
  };

  const handleCreateSubmit = async (payload: Record<string, unknown>) => {
    const token = await getToken();
    if (!token) throw new Error("Authentication token unavailable");
    return await createMyPlant(token, payload);
  };

  const handleCreateSuccess = (res: unknown) => {
    const created = res as {
      plant_id: string;
      one_time_device_credentials?: OneTimeDeviceCredential[];
      viewer_token?: string;
      broker_reloaded?: boolean;
    };
    setShowCreateForm(false);
    refreshPlants(created.plant_id);
    if (
      (created.one_time_device_credentials && created.one_time_device_credentials.length > 0) ||
      created.viewer_token
    ) {
      setModalCredentials(created.one_time_device_credentials || null);
      setModalViewerToken(created.viewer_token || null);
      setModalPlantId(created.plant_id);
      setModalBrokerReloaded(created.broker_reloaded);
      setCredModalSource("create");
      setCredModalOpen(true);
    }
  };

  const handleCopyCommand = async (text: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      setCmdCopied(true);
      setTimeout(() => setCmdCopied(false), 2000);
    }
  };

  const handleCopyJson = async (text: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      setJsonCopied(true);
      setTimeout(() => setJsonCopied(false), 2000);
    }
  };

  // Derive first machine code and signal code from detail for canonical example
  const activePlantSummary = plants.find((p) => p.plant_id === selectedPlantId);
  const firstMachine = selectedPlantDetail?.areas?.[0]?.machines?.[0];
  const machineCode = firstMachine?.machine_code || "press_01";
  const signalCode = firstMachine?.signals?.[0]?.signal_code || "pressure_bar";
  const mosquittoCmd = selectedPlantId
    ? buildMosquittoPubCommand(selectedPlantId, machineCode, signalCode)
    : "";
  const telemetryJson = selectedPlantId
    ? buildTelemetryExampleJson(selectedPlantId, machineCode, signalCode)
    : "";

  const isAtQuota = !canCreatePlant(plants.length, 3);

  if (!mounted || !isLoaded || !isSignedIn) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3">
        <div className="w-8 h-8 rounded-full border-2 border-blue-600 border-t-transparent animate-spin" />
        <span className="text-xs text-slate-500 font-medium">Verifying session...</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 max-w-6xl mx-auto py-4 px-4">
      {/* Credentials Modal */}
      <AdminCredentialsModal
        isOpen={credModalOpen}
        source={credModalSource}
        credentials={modalCredentials}
        viewerToken={modalViewerToken}
        plantId={modalPlantId || selectedPlantId || undefined}
        brokerReloaded={modalBrokerReloaded}
        onClose={() => setCredModalOpen(false)}
      />

      {/* Delete Confirmation Modal */}
      <AdminDeleteModal
        isOpen={deleteModalOpen}
        isDeleting={isDeleting}
        plantId={selectedPlantId || ""}
        plantName={activePlantSummary?.name || selectedPlantId || ""}
        isSystemPlant={false}
        error={deleteError}
        onConfirm={handleDeleteConfirm}
        onClose={() => {
          setDeleteModalOpen(false);
          setDeleteError(null);
        }}
      />

      {/* Top Banner / Quota Badge */}
      <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">🌱</span>
            <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">
              My Manufacturing Plants
            </h1>
          </div>
          <p className="text-xs sm:text-sm text-slate-500 mt-1 max-w-2xl leading-relaxed">
            Manage your personal manufacturing facilities, rotate device credentials and viewer tokens,
            and inspect device integration topics.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div
            className={`px-3.5 py-1.5 rounded-full text-xs font-bold border transition-colors ${
              isAtQuota
                ? "bg-amber-50 text-amber-800 border-amber-300"
                : "bg-blue-50 text-blue-700 border-blue-200"
            }`}
          >
            {formatPlantQuota(plants.length, 3)}
          </div>

          <button
            type="button"
            disabled={isAtQuota && !showCreateForm}
            onClick={() => setShowCreateForm((prev) => !prev)}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all shadow-xs flex items-center gap-1.5 cursor-pointer ${
              showCreateForm
                ? "bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300"
                : isAtQuota
                ? "bg-slate-100 text-slate-400 border border-slate-200 cursor-not-allowed"
                : "bg-blue-600 hover:bg-blue-700 text-white"
            }`}
          >
            {showCreateForm ? (
              <span>✕ Close Form</span>
            ) : (
              <>
                <span>+</span>
                <span>Register New Plant</span>
              </>
            )}
          </button>
        </div>
      </div>

      {errorMessage && (
        <div
          role="alert"
          className="p-4 rounded-2xl bg-rose-50 border border-rose-300 text-rose-900 text-xs font-medium flex items-center gap-2"
        >
          <span className="font-bold text-base text-rose-600">✕</span>
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Creation Form Accordion */}
      {showCreateForm && (
        <div className="animate-in fade-in zoom-in-95 duration-150">
          <div className="flex items-center justify-between pb-3">
            <h2 className="text-sm font-bold text-slate-800 uppercase tracking-wider">
              Register Personal Facility
            </h2>
          </div>
          <PlantCreateForm
            onSubmit={handleCreateSubmit}
            onSuccess={handleCreateSuccess}
            onCancel={() => setShowCreateForm(false)}
            isSelfService={true}
          />
        </div>
      )}

      {/* Plants Grid & Selected Detail */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Plant Facilities List */}
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between px-1">
            <h2 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Facilities ({plants.length})
            </h2>
            {isLoadingPlants && (
              <div className="w-3.5 h-3.5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
            )}
          </div>

          {plants.length === 0 && !isLoadingPlants ? (
            <div className="bg-white rounded-3xl p-8 border border-dashed border-slate-300 text-center flex flex-col items-center gap-3">
              <span className="text-3xl">🏭</span>
              <div className="text-sm font-bold text-slate-700">No facilities registered yet</div>
              <p className="text-xs text-slate-500 max-w-xs">
                You have not registered any manufacturing plants. Use the button above to register your first facility.
              </p>
              {!showCreateForm && (
                <button
                  type="button"
                  onClick={() => setShowCreateForm(true)}
                  className="mt-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-xl shadow-xs transition-colors cursor-pointer"
                >
                  Create Your First Plant
                </button>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-2.5">
              {plants.map((p) => {
                const isSelected = p.plant_id === selectedPlantId;
                return (
                  <button
                    key={p.plant_id}
                    type="button"
                    onClick={() => setSelectedPlantId(p.plant_id)}
                    className={`w-full text-left p-4 rounded-2xl border transition-all cursor-pointer flex flex-col gap-1.5 ${
                      isSelected
                        ? "bg-blue-50/70 border-blue-400 shadow-xs ring-2 ring-blue-100"
                        : "bg-white border-slate-200 hover:border-slate-300 hover:bg-slate-50/50 shadow-2xs"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-slate-900 truncate">
                        {p.name}
                      </span>
                      <span className="text-[10px] uppercase font-mono font-bold px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 border border-slate-200">
                        {p.role}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[11px] font-mono text-slate-500">
                      <span>{p.plant_id}</span>
                      <span>🔒 Private</span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Columns: Detail & Connect Device Cards */}
        <div className="lg:col-span-2 flex flex-col gap-6">
          {selectedPlantId && activePlantSummary ? (
            <>
              {/* Detail Card */}
              <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-xs flex flex-col gap-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-5">
                  <div>
                    <h2 className="text-lg font-bold text-slate-900 tracking-tight flex items-center gap-2">
                      <span>{activePlantSummary.name}</span>
                      <span className="text-xs font-mono font-medium text-slate-400">
                        ({activePlantSummary.plant_id})
                      </span>
                    </h2>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Timezone: <span className="font-semibold text-slate-700">{activePlantSummary.timezone}</span> •
                      Role: <span className="font-semibold text-slate-700">{activePlantSummary.role}</span>
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handleOpenDashboard(selectedPlantId)}
                      className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-bold shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer"
                    >
                      <span>📊 Open dashboard</span>
                    </button>
                  </div>
                </div>

                {isLoadingDetail ? (
                  <div className="flex items-center justify-center py-8 gap-2 text-xs text-slate-400">
                    <div className="w-4 h-4 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
                    <span>Loading definition...</span>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="p-4 rounded-2xl bg-slate-50 border border-slate-200 flex flex-col gap-1">
                      <span className="text-[11px] font-semibold text-slate-500">Topology Structure</span>
                      <span className="text-sm font-bold text-slate-800">
                        {selectedPlantDetail?.areas?.length || 0} Areas,{" "}
                        {selectedPlantDetail?.areas?.reduce((acc: number, a) => acc + (a.machines?.length || 0), 0) || 0} Machines
                      </span>
                    </div>

                    <div className="p-4 rounded-2xl bg-slate-50 border border-slate-200 flex flex-col gap-1">
                      <span className="text-[11px] font-semibold text-slate-500">Device Username</span>
                      <span className="text-sm font-bold font-mono text-slate-800">
                        {selectedPlantDetail?.device_usernames?.[0] || `device_${selectedPlantId}`}
                      </span>
                    </div>
                  </div>
                )}

                {/* Management Actions */}
                <div className="flex flex-wrap items-center gap-3 pt-4 border-t border-slate-100">
                  <button
                    type="button"
                    onClick={handleRotateCredentials}
                    className="px-3.5 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold border border-slate-200 transition-colors cursor-pointer"
                  >
                    🔑 Rotate device credentials
                  </button>
                  <button
                    type="button"
                    onClick={handleRotateViewerToken}
                    className="px-3.5 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold border border-slate-200 transition-colors cursor-pointer"
                  >
                    🔄 Rotate viewer token
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeleteModalOpen(true)}
                    className="ml-auto px-3.5 py-2 rounded-xl bg-rose-50 hover:bg-rose-100 text-rose-700 text-xs font-semibold border border-rose-200 transition-colors cursor-pointer"
                  >
                    🗑️ Delete facility
                  </button>
                </div>
              </div>

              {/* Connect a Device Card */}
              <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-xs flex flex-col gap-5">
                <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-2.5">
                    <span className="text-base">📡</span>
                    <h3 className="text-sm font-bold uppercase tracking-wider text-slate-800">
                      Connect a Device
                    </h3>
                  </div>
                  <span className="text-[11px] font-mono text-slate-400">MQTT v3.1.1 / v5.0</span>
                </div>

                <div className="p-3.5 rounded-2xl bg-amber-50 border border-amber-200 text-amber-900 text-xs leading-relaxed flex flex-col gap-1">
                  <div className="font-bold flex items-center gap-1.5 text-amber-800">
                    <span>ℹ️</span>
                    <span>Internal Broker Network Notice</span>
                  </div>
                  <p>
                    The MQTT broker runs internally within the Docker bridge network today (port 1883 is not published to the host).
                    Use <code className="font-mono bg-amber-100/70 px-1 py-0.5 rounded text-[11px]">docker compose exec broker mosquitto_pub</code> to publish telemetry directly inside the container environment.
                  </p>
                </div>

                {/* Ingest Topic */}
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-semibold text-slate-700">MQTT Ingest Topic</span>
                  <div className="px-3.5 py-2 rounded-xl bg-slate-50 border border-slate-300 font-mono text-xs text-blue-700 select-all">
                    plants/{selectedPlantId}/assets/{machineCode}/telemetry
                  </div>
                </div>

                {/* Example Envelope JSON */}
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-700">Canonical Ingest Envelope</span>
                    <button
                      type="button"
                      onClick={() => handleCopyJson(telemetryJson)}
                      className="text-[11px] font-semibold text-blue-600 hover:text-blue-800 cursor-pointer"
                    >
                      {jsonCopied ? "✓ Copied JSON" : "Copy JSON"}
                    </button>
                  </div>
                  <pre className="p-3.5 rounded-xl bg-slate-900 text-slate-100 font-mono text-[11px] overflow-x-auto leading-relaxed">
                    {telemetryJson}
                  </pre>
                </div>

                {/* Copy-Paste CLI Command */}
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-700">
                      Copy-Paste Publisher Command (<span className="text-rose-600 font-mono">&lt;password&gt;</span> placeholder)
                    </span>
                    <button
                      type="button"
                      onClick={() => handleCopyCommand(mosquittoCmd)}
                      className="text-[11px] font-semibold text-blue-600 hover:text-blue-800 cursor-pointer"
                    >
                      {cmdCopied ? "✓ Copied Command" : "Copy Command"}
                    </button>
                  </div>
                  <div className="p-3.5 rounded-xl bg-slate-900 text-emerald-400 font-mono text-[11px] overflow-x-auto whitespace-pre-wrap break-all select-all">
                    {mosquittoCmd}
                  </div>
                  <span className="text-[11px] text-slate-400">
                    Replace <code className="font-mono text-rose-600">&lt;password&gt;</code> with your device password displayed upon creation or rotation.
                  </span>
                </div>
              </div>
            </>
          ) : (
            <div className="bg-white rounded-3xl p-12 border border-slate-200 text-center flex flex-col items-center gap-2 text-slate-400">
              <span className="text-3xl">👈</span>
              <span className="text-xs font-medium">Select a facility from the list on the left to view details and device instructions</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
