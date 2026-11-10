import { t } from "../i18n";
import type { FinancePeriod } from "../types";

const OPTIONS: {
  value: FinancePeriod;
  key: "period.30d" | "period.90d" | "period.all";
}[] = [
  { value: "30d", key: "period.30d" },
  { value: "90d", key: "period.90d" },
  { value: "all", key: "period.all" },
];

export default function PeriodPicker({
  value,
  onChange,
}: {
  value: FinancePeriod;
  onChange: (period: FinancePeriod) => void;
}) {
  return (
    <div className="inline-flex gap-1 rounded-xl border border-line bg-panel p-1 text-sm">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
          className={`min-h-10 rounded-lg px-3.5 font-semibold transition ${
            value === option.value
              ? "bg-accent-soft text-ink"
              : "text-ink-muted hover:text-ink"
          }`}
        >
          {t(option.key)}
        </button>
      ))}
    </div>
  );
}
