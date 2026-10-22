"use client";

import React, { useReducer } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAdminAuth } from "../../layout";
import {
  createAdminPlant,
  credentialModalReducer,
  initialCredentialModalState,
} from "../../../../lib/admin-api";
import { AdminCredentialsModal } from "../../../../components/admin/AdminCredentialsModal";
import { PlantCreateForm } from "../../../../components/admin/PlantCreateForm";

export default function NewPlantPage() {
  const router = useRouter();
  const { adminToken } = useAdminAuth();

  // Credential Modal State Machine
  const [modalState, dispatchModal] = useReducer(
    credentialModalReducer,
    initialCredentialModalState
  );

  const handleSubmit = async (payload: Record<string, unknown>) => {
    return await createAdminPlant(adminToken, payload);
  };

  const handleSuccess = (res: unknown) => {
    const created = res as {
      one_time_device_credentials?: Array<{ username: string; password?: string; client_id: string }>;
      broker_reloaded?: boolean;
    };
    if (created.one_time_device_credentials && created.one_time_device_credentials.length > 0) {
      dispatchModal({
        type: "OPEN_CREDENTIALS",
        source: "create",
        credentials: created.one_time_device_credentials,
        brokerReloaded: created.broker_reloaded,
      });
    } else {
      router.push("/admin");
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

      {/* Reusable Plant Create Form */}
      <PlantCreateForm
        onSubmit={handleSubmit}
        onSuccess={handleSuccess}
        onCancel={() => router.push("/admin")}
        isSelfService={false}
      />
    </div>
  );
}
