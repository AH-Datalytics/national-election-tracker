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
      <body className="min-h-screen flex flex-col">
        <header className="border-b border-gray-200">
          <div className="max-w-6xl mx-auto px-4 py-3 flex items-baseline justify-between">
            <Link href="/" className="text-lg font-bold tracking-tight" style={{ fontFamily: "var(--font-serif)", color: "var(--color-primary)" }}>
              National Election Tracker
            </Link>
            <nav className="flex gap-6 text-sm">
              <Link href="/" className="hover:text-[var(--color-accent)]">Home</Link>
              <Link href="/la" className="hover:text-[var(--color-accent)]">Louisiana</Link>
              <Link href="/in" className="hover:text-[var(--color-accent)]">Indiana</Link>
              <Link href="/oh" className="hover:text-[var(--color-accent)]">Ohio</Link>
            </nav>
          </div>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="border-t border-gray-200 py-4 text-center text-xs text-[var(--color-muted)]">
          Built by <a href="https://ahdatalytics.com" className="hover:text-[var(--color-accent)]">AH Datalytics</a>
        </footer>
      </body>
    </html>
  );
}
