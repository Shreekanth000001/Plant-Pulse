import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import { WebSocketProvider } from "../context/WebSocketContext";
import { AppShell } from "../components/layout/AppShell";
import { QCAlertToastContainer } from "../components/notifications/QCAlertToast";

export const metadata: Metadata = {
  title: "PlantPulse — Industrial Operations & Quality Dashboard",
  description:
    "Real-time manufacturing telemetry, OEE efficiency, and unit quality traceability",
  icons: {
    icon: "/icon.svg",
    shortcut: "/icon.svg",
    apple: "/icon.svg",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col text-slate-900 bg-slate-50 selection:bg-blue-100 selection:text-blue-900">
        <ClerkProvider>
          <WebSocketProvider>
            <QCAlertToastContainer />
            <AppShell>
              <Suspense
                fallback={
                  <div className="flex flex-col items-center justify-center min-h-[50vh] gap-3">
                    <div className="w-8 h-8 rounded-full border-2 border-blue-600 border-t-transparent animate-spin" />
                    <div className="text-xs text-slate-500 font-medium">
                      Loading telemetry stream...
                    </div>
                  </div>
                }
              >
                {children}
              </Suspense>
            </AppShell>
          </WebSocketProvider>
        </ClerkProvider>
      </body>
    </html>
  );
}