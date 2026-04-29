import USMap from "@/components/USMap";

export default function HomePage() {
  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold mb-2" style={{ fontFamily: "var(--font-serif)", color: "var(--color-primary)" }}>
          National Election Tracker
        </h1>
        <p className="text-[var(--color-muted)]">
          Precinct-level results for every race, every state
        </p>
      </div>
      <USMap />
      <div className="mt-6 flex justify-center gap-8 text-sm text-[var(--color-muted)]">
        <span>3 states</span>
        <span>Precinct-level results</span>
        <span>2019 – present</span>
      </div>
    </div>
  );
}
