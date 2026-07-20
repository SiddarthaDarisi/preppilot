import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "PrepPilot — Dashboard",
};

export default function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return children;
}
