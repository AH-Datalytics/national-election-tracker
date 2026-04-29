import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "National Election Tracker",
  description: "Precinct-level election results for every race, every state",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col" style={{ background: "var(--color-background)" }}>
        <header style={{ borderBottom: "1px solid var(--color-border)" }}>
          <div style={{ maxWidth: 1200, margin: "0 auto", padding: "12px 16px", display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
            <Link href="/" style={{ fontFamily: "var(--font-serif)", fontSize: "1.125rem", fontWeight: 700, color: "var(--color-foreground)", textDecoration: "none" }}>
              National Election Tracker
            </Link>
            <nav style={{ display: "flex", gap: 24, fontSize: "0.875rem" }}>
              <Link href="/" style={{ color: "var(--color-foreground)", textDecoration: "none" }}>Home</Link>
              <Link href="/la" style={{ color: "var(--color-foreground)", textDecoration: "none" }}>Louisiana</Link>
              <Link href="/in" style={{ color: "var(--color-foreground)", textDecoration: "none" }}>Indiana</Link>
              <Link href="/oh" style={{ color: "var(--color-foreground)", textDecoration: "none" }}>Ohio</Link>
            </nav>
          </div>
        </header>
        <main className="flex-1">{children}</main>
        <footer style={{ borderTop: "1px solid var(--color-border)", padding: "16px 0", textAlign: "center", fontSize: "0.75rem", color: "var(--color-muted)" }}>
          Powered by{" "}
          <a href="https://ahdatalytics.com" target="_blank" rel="noopener noreferrer" style={{ color: "var(--color-accent)", textDecoration: "none" }}>
            AH Datalytics
          </a>
        </footer>
      </body>
    </html>
  );
}
