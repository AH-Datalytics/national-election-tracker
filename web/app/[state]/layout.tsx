import Link from "next/link";
import { notFound } from "next/navigation";
import { STATE_NAMES, STATES_WITH_DATA } from "@/lib/constants";

export default async function StateLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ state: string }>;
}) {
  const { state } = await params;
  const code = state.toUpperCase();
  if (!STATES_WITH_DATA.includes(code)) notFound();
  const name = STATE_NAMES[code] ?? code;

  return (
    <div>
      {/* Breadcrumb */}
      <div style={{ borderBottom: "1px solid var(--color-border)" }}>
        <div
          style={{
            maxWidth: 1200,
            margin: "0 auto",
            padding: "10px 16px",
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: "0.8125rem",
            color: "var(--color-muted)",
          }}
        >
          <Link
            href="/"
            style={{
              color: "var(--color-muted)",
              textDecoration: "none",
            }}
          >
            Home
          </Link>
          <span style={{ color: "#ccc" }}>/</span>
          <span
            style={{
              fontFamily: "var(--font-serif)",
              fontWeight: 600,
              color: "var(--color-foreground)",
            }}
          >
            {name}
          </span>
        </div>
      </div>

      {/* Sub-navigation tabs */}
      <div style={{ borderBottom: "1px solid var(--color-border)" }}>
        <nav
          style={{
            maxWidth: 1200,
            margin: "0 auto",
            padding: "0 16px",
            display: "flex",
            gap: 0,
          }}
        >
          <StateNavLink href={`/${state}`} label="Overview" />
          <StateNavLink href={`/${state}/elections`} label="Elections" />
          <StateNavLink href={`/${state}/live`} label="Live" />
        </nav>
      </div>

      {children}
    </div>
  );
}

function StateNavLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      style={{
        padding: "10px 16px",
        fontSize: "0.875rem",
        fontWeight: 500,
        color: "var(--color-foreground)",
        textDecoration: "none",
        borderBottom: "2px solid transparent",
        transition: "border-color 0.15s, color 0.15s",
        marginBottom: -1,
      }}
    >
      {label}
    </Link>
  );
}
