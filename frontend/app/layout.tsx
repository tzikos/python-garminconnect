import type { Metadata } from "next";
import { Toaster } from "sonner";
import { Sidebar } from "@/components/sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Garmin Coach",
  description: "Multi-sport training planner",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen flex">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">{children}</main>
        <Toaster theme="dark" richColors closeButton position="top-right" />
      </body>
    </html>
  );
}
