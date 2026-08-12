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
    <div className="inline-flex rounded-lg border border-zinc-700 bg-zinc-900 p-0.5 text-sm">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          onClick={() => onChange(option.value)}
          className={`rounded-md px-3 py-1 transition ${
            value === option.value
              ? "bg-purple-600 text-white"
              : "text-zinc-400 hover:text-zinc-200"
          }`}
        >
          {t(option.key)}
        </button>
      ))}
    </div>
  );
}
