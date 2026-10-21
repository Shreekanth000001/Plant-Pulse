"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import {
  checkAdminMounted,
  checkAdminHealth,
  formatAdminErrorMessage,
  AdminApiError,
} from "../../lib/admin-api";
import { AdminTokenEntryCard } from "../../components/admin/AdminTokenEntryCard";
import { AdminUnmountedScreen } from "../../components/admin/AdminUnmountedScreen";
import { AdminHeader } from "../../components/admin/AdminHeader";

interface AdminAuthContextType {
  adminToken: string;
  logout: () => void;
  reportApiError: (err: unknown) => void;
}

const AdminAuthContext = createContext<AdminAuthContextType | null>(null);

export function useAdminAuth(): AdminAuthContextType {
  const ctx = useContext(AdminAuthContext);
  if (!ctx) {
    throw new Error("useAdminAuth must be used within AdminLayout");
  }
  return ctx;
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  // Master token held strictly in React memory (useState).
  // Zero sessionStorage, zero localStorage, zero URL exposure, zero console logging.
  // On reload (F5), memory resets to null and shows the token entry card again.
  const [adminToken, setAdminToken] = useState<string | null>(null);
  const [isMounted, setIsMounted] = useState<boolean | null>(null);
  const [isCheckingMounted, setIsCheckingMounted] = useState(true);
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [lockoutSeconds, setLockoutSeconds] = useState<number | null>(null);

  // Probe backend to see if admin endpoints are mounted
  const verifyMounted = useCallback(async () => {
    setIsCheckingMounted(true);
    setAuthError(null);
    try {
      const mounted = await checkAdminMounted();
      setIsMounted(mounted);
    } catch {
      setIsMounted(true);
    } finally {
      setIsCheckingMounted(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    checkAdminMounted()
      .then((mounted) => {
        if (!active) return;
        setIsMounted(mounted);
        setIsCheckingMounted(false);
      })
      .catch(() => {
        if (!active) return;
        setIsMounted(true);
        setIsCheckingMounted(false);
      });
    return () => {
      active = false;
    };
  }, []);

  // Lockout countdown timer when 429 received
  useEffect(() => {
    if (lockoutSeconds === null || lockoutSeconds <= 0) return;
    const interval = setInterval(() => {
      setLockoutSeconds((prev) => {
        if (prev === null || prev <= 1) {
          clearInterval(interval);
          return null;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [lockoutSeconds]);

  // Handle token authentication attempt
  const handleAuthenticate = async (token: string) => {
    setIsAuthenticating(true);
    setAuthError(null);
    try {
      await checkAdminHealth(token);
      // Valid token -> retain in memory only
      setAdminToken(token);
      setAuthError(null);
      setLockoutSeconds(null);
    } catch (err: unknown) {
      if (err instanceof AdminApiError) {
        if (err.isUnmounted) {
          setIsMounted(false);
          return;
        }
        if (err.isThrottled && err.retryAfter) {
          setLockoutSeconds(err.retryAfter);
        }
      }
      setAdminToken(null);
      setAuthError(formatAdminErrorMessage(err));
    } finally {
      setIsAuthenticating(false);
    }
  };

  const handleLogout = useCallback(() => {
    setAdminToken(null);
    setAuthError(null);
  }, []);

  const reportApiError = useCallback((err: unknown) => {
    if (err instanceof AdminApiError) {
      if (err.isUnauthorized) {
        // Clear token from memory on 401
        setAdminToken(null);
        setAuthError("Session expired or token invalid. Please re-authenticate.");
        return;
      }
      if (err.isThrottled && err.retryAfter) {
        setLockoutSeconds(err.retryAfter);
      }
      if (err.isUnmounted) {
        setIsMounted(false);
        return;
      }
    }
    setAuthError(formatAdminErrorMessage(err));
  }, []);

  if (isCheckingMounted) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] gap-3">
        <div className="w-8 h-8 rounded-full border-2 border-slate-900 border-t-transparent animate-spin" />
        <div className="text-xs text-slate-500 font-medium">
          Checking admin endpoints configuration...
        </div>
      </div>
    );
  }

  if (isMounted === false) {
    return <AdminUnmountedScreen onRetry={verifyMounted} />;
  }

  if (!adminToken) {
    return (
      <div className="w-full py-8">
        <AdminTokenEntryCard
          onSubmit={handleAuthenticate}
          error={authError}
          isSubmitting={isAuthenticating}
          lockoutSeconds={lockoutSeconds}
        />
      </div>
    );
  }

  return (
    <AdminAuthContext.Provider value={{ adminToken, logout: handleLogout, reportApiError }}>
      <div className="w-full flex flex-col">
        <AdminHeader onLogout={handleLogout} />
        {children}
      </div>
    </AdminAuthContext.Provider>
  );
}
