import type { Metadata } from "next";
import "@fontsource-variable/geist";
import "./globals.css";
import "./viewer.css";
export const metadata: Metadata = {
  title: "FightLens — The fight, made visible",
  description:
    "An interactive FightLens review prototype with impact mirrors, evidence replay, and simulated prediction-market quotes.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
