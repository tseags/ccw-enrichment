type Props = {
  confidence: number;
};

export function ConfidencePill({ confidence }: Props) {
  const band = confidence >= 0.85 ? "high" : confidence >= 0.6 ? "medium" : "low";
  const tone = band === "high" ? "bg-emerald-100" : band === "medium" ? "bg-amber-100" : "bg-red-100";
  return (
    <span className={`rounded px-2 py-1 text-xs ${tone}`}>
      {band} ({Math.round(confidence * 100)}%)
    </span>
  );
}
