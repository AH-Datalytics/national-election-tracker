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
      <div className="border-b border-gray-100">
        <div className="max-w-6xl mx-auto px-4 py-2 flex items-center gap-2 text-sm text-[var(--color-muted)]">
          <Link href="/" className="hover:text-[var(--color-accent)]">Home</Link>
          <span>/</span>
          <span className="font-medium text-gray-900">{name}</span>
        </div>
        <div className="max-w-6xl mx-auto px-4 pb-2 flex gap-4 text-sm">
          <Link href={`/${state}`} className="hover:text-[var(--color-accent)]">Overview</Link>
          <Link href={`/${state}/elections`} className="hover:text-[var(--color-accent)]">Elections</Link>
          <Link href={`/${state}/live`} className="hover:text-[var(--color-accent)]">Live</Link>
        </div>
      </div>
      {children}
    </div>
  );
}
