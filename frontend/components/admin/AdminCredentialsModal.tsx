"use client";

import React, { useState } from "react";
import type { OneTimeDeviceCredential } from "../../lib/admin-api";

interface AdminCredentialsModalProps {
  isOpen: boolean;
  source: "create" | "rotate" | "viewer-token-rotate" | null;
  credentials?: OneTimeDeviceCredential[] | null;
  viewerToken?: string | null;
  plantId?: string | null;
  brokerReloaded?: boolean;
  onClose: () => void;
}

export function AdminCredentialsModal({
  isOpen,
  source,
  credentials,
  viewerToken,
  plantId,
  brokerReloaded,
  onClose,
}: AdminCredentialsModalProps) {
  const [copied, setCopied] = useState(false);
  const [copiedToken, setCopiedToken] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);
  const [showPassword, setShowPassword] = useState(true);

  if (!isOpen || ((!credentials || credentials.length === 0) && !viewerToken)) {
    return null;
  }

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const shareableUrl =
    plantId && viewerToken
      ? `${origin}/?plant=${encodeURIComponent(plantId)}&token=${encodeURIComponent(viewerToken)}`
      : viewerToken
      ? `${origin}/?token=${encodeURIComponent(viewerToken)}`
      : "";

  const handleCopy = async () => {
    try {
      const parts: string[] = [];
      if (credentials && credentials.length > 0) {
        parts.push(
          credentials
            .map(
              (c, idx) =>
                `# Credential ${idx + 1}\nMQTT_USER=${c.username}\nMQTT_PASSWORD=${c.password || ""}\nMQTT_CLIENT_ID=${c.client_id}`
            )
            .join("\n\n")
        );
      }
      if (viewerToken) {
        parts.push(`# Viewer Token\nVIEWER_TOKEN=${viewerToken}`);
        if (shareableUrl) {
          parts.push(`# Direct Shareable URL\nSHAREABLE_URL=${shareableUrl}`);
        }
      }
      const formatted = parts.join("\n\n");

      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(formatted);
        setCopied(true);
        setTimeout(() => setCopied(false), 2500);
      }
    } catch {
      // ignore clipboard failures in headless environments
    }
  };

  const handleCopyToken = async () => {
    if (!viewerToken) return;
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(viewerToken);
        setCopiedToken(true);
        setTimeout(() => setCopiedToken(false), 2000);
      }
    } catch {
      // ignore clipboard failures in headless environments
    }
  };

  const handleCopyLink = async () => {
    if (!shareableUrl) return;
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(shareableUrl);
        setCopiedLink(true);
        setTimeout(() => setCopiedLink(false), 2000);
      }
    } catch {
      // ignore clipboard failures in headless environments
    }
  };

  const title =
    source === "viewer-token-rotate"
      ? "Rotated Viewer Token"
      : source === "rotate"
      ? "Rotated Device Credentials"
      : !credentials || credentials.length === 0
      ? "Viewer Access Token & Share Link"
      : "One-Time Initial Device Credentials & Viewer Token";

  const subtitle =
    source === "viewer-token-rotate"
      ? "Save or share this new viewer token now. Previous viewer tokens for this facility are revoked."
      : "Save these credentials now. Plain-text passwords cannot be displayed again.";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="cred-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs"
    >
      <div className="bg-white rounded-3xl max-w-lg w-full p-6 sm:p-8 shadow-2xl border-2 border-emerald-500/20 flex flex-col gap-6 animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-start justify-between gap-4 pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-emerald-50 text-emerald-700 flex items-center justify-center text-lg font-bold">
              🔑
            </div>
            <div>
              <h3
                id="cred-modal-title"
                className="text-base sm:text-lg font-bold text-slate-900 tracking-tight"
              >
                {title}
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                {subtitle}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close modal"
            className="text-slate-400 hover:text-slate-700 p-1 text-sm font-semibold rounded-lg hover:bg-slate-100 transition-colors"
          >
            ✕
          </button>
        </div>

        <div className="p-3.5 rounded-2xl bg-amber-50 border border-amber-200 text-amber-900 text-xs flex items-start gap-2.5">
          <span className="font-bold text-base leading-none text-amber-700">⚠️</span>
          <p className="leading-relaxed">
            <strong className="font-semibold">Copy and store securely:</strong> Once you dismiss this dialog, plain-text credentials and tokens cannot be displayed again.
          </p>
        </div>

        {brokerReloaded === false && (
          <div className="p-3 rounded-xl bg-orange-50 border border-orange-200 text-orange-900 text-xs flex items-center gap-2">
            <span>ℹ️</span>
            <span>Mosquitto reload returned false; broker will pick up changes on next restart.</span>
          </div>
        )}

        <div className="flex flex-col gap-4 max-h-[45vh] overflow-y-auto pr-1">
          {/* Read-Only Viewer Token Card */}
          {viewerToken && (
            <div className="bg-slate-50 border border-blue-200 rounded-2xl p-4 flex flex-col gap-3 font-sans text-xs">
              <div className="flex items-center justify-between text-slate-500 text-[11px] font-semibold border-b border-slate-200 pb-1.5">
                <span className="flex items-center gap-1.5 text-blue-900 font-bold">
                  <span>🔗</span> Read-Only Viewer Access Token
                </span>
                <span className="px-2 py-0.5 rounded-md bg-blue-100 text-blue-800 text-[10px] font-semibold">
                  SHARABLE
                </span>
              </div>

              <p className="text-slate-600 text-xs leading-relaxed">
                Share this token or 1-click link with shift managers, operators, or executives to grant instant read-only telemetry dashboard access without requiring an account.
              </p>

              {/* Raw Token */}
              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-slate-600">Token:</span>
                  <button
                    type="button"
                    onClick={handleCopyToken}
                    className="text-[11px] font-semibold text-blue-600 hover:text-blue-800 transition-colors cursor-pointer"
                  >
                    {copiedToken ? "✓ Copied Token" : "Copy Token"}
                  </button>
                </div>
                <div className="p-2.5 rounded-xl bg-white border border-slate-200 font-mono text-[11px] text-slate-900 select-all break-all">
                  {viewerToken}
                </div>
              </div>

              {/* Direct Shareable URL */}
              {shareableUrl && (
                <div className="flex flex-col gap-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-semibold text-slate-600">Direct Share Link (1-Click Access):</span>
                    <button
                      type="button"
                      onClick={handleCopyLink}
                      className="text-[11px] font-semibold text-blue-600 hover:text-blue-800 transition-colors cursor-pointer"
                    >
                      {copiedLink ? "✓ Copied Link" : "Copy Share Link"}
                    </button>
                  </div>
                  <div className="p-2.5 rounded-xl bg-blue-50/70 border border-blue-200 font-mono text-[11px] text-blue-900 select-all break-all">
                    {shareableUrl}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* MQTT Device Credentials */}
          {credentials && credentials.map((cred, idx) => (
            <div
              key={cred.username + idx}
              className="bg-slate-50 border border-slate-200 rounded-2xl p-4 flex flex-col gap-2.5 font-mono text-xs"
            >
              <div className="flex items-center justify-between text-slate-500 text-[11px] font-sans font-semibold border-b border-slate-200 pb-1.5">
                <span>Credential #{idx + 1}</span>
                <span className="px-2 py-0.5 rounded-md bg-emerald-100 text-emerald-800 text-[10px]">
                  ACTIVE
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500 font-sans text-[11px]">Username:</span>
                <span className="font-semibold text-slate-900 select-all">{cred.username}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500 font-sans text-[11px]">Password:</span>
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-emerald-700 select-all">
                    {showPassword ? cred.password || "[NOT SET]" : "••••••••••••••••"}
                  </span>
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="text-[10px] text-slate-400 hover:text-slate-700 underline font-sans"
                  >
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500 font-sans text-[11px]">Client ID:</span>
                <span className="text-slate-700 select-all">{cred.client_id}</span>
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between gap-3 pt-4 border-t border-slate-100">
          <button
            type="button"
            onClick={handleCopy}
            className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 border transition-colors ${
              copied
                ? "bg-emerald-50 text-emerald-700 border-emerald-300"
                : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50 hover:border-slate-400"
            }`}
          >
            <span>{copied ? "✓" : "📋"}</span>
            <span>{copied ? "Copied to Clipboard!" : "Copy All Credentials"}</span>
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-5 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold transition-colors shadow-xs"
          >
            {source === "viewer-token-rotate" ? "Close" : "I have saved credentials & Close"}
          </button>
        </div>
      </div>
    </div>
  );
}
