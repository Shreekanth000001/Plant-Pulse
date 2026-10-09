import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Suspense } from "react";
import "./globals.css";
import { WebSocketProvider } from "../context/WebSocketContext";
import { Header } from "../components/layout/Header";
import { QCAlertToastContainer } from "../components/notifications/QCAlertToast";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "PlantPulse // Industrial Telemetry Dashboard",
  description:
    "Real-time SCADA telemetry and quality traceability dashboard for membrane manufacturing facility",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased dark`}
    >
      <body className="min-h-full flex flex-col bg-[#080c14] text-slate-200">
        <WebSocketProvider>
          <Suspense fallback={<div className="h-14 border-b border-slate-800 bg-[#080c14]" />}>
            <Header />
          </Suspense>
          <QCAlertToastContainer />
          <main className="flex-1 w-full max-w-7xl mx-auto px-4 lg:px-8 py-6">
            <Suspense
              fallback={
                <div className="flex flex-col items-center justify-center min-h-[50vh] gap-3 font-mono">
                  <div className="w-8 h-8 rounded-full border-2 border-cyan-500 border-t-transparent animate-spin" />
                  <div className="text-xs text-slate-400">
                    LOADING SCADA SUBSYSTEM...
                  </div>
                </div>
              }
            >
              {children}
            </Suspense>
          </main>
          <footer className="w-full border-t border-slate-800/80 py-3 px-4 text-center font-mono text-[11px] text-slate-500">
            PlantPulse Manufacturing OS • Facility Line 01 • SCADA Telemetry Stream
          </footer>
        </WebSocketProvider>
      </body>
    </html>
  );
}
