import type { Metadata } from "next";
import "./globals.css";
import Navbar from "@/components/ui/Navbar";

export const metadata: Metadata = {
  title: "InvestIQ — AI-Powered Investing Education",
  description: "Master crypto, forex, stocks, and options with AI-powered lessons, quizzes, and personalized coaching.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-screen" style={{ background: "var(--background)", color: "var(--foreground)" }}>
        <Navbar />
        <main className="pt-16">{children}</main>
      </body>
    </html>
  );
}
