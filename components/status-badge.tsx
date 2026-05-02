type Props = {
  label: string;
};

export function StatusBadge({ label }: Props) {
  const tone =
    label.includes("fail") || label.includes("critical")
      ? "bg-red-100 text-red-700"
      : label.includes("review") || label.includes("pending")
        ? "bg-amber-100 text-amber-700"
        : "bg-emerald-100 text-emerald-700";
  return <span className={`rounded px-2 py-1 text-xs font-medium ${tone}`}>{label}</span>;
}
