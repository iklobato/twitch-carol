import type { FinancePeriod } from '../types'

const OPTIONS: { value: FinancePeriod; label: string }[] = [
  { value: '30d', label: '30 dias' },
  { value: '90d', label: '90 dias' },
  { value: 'all', label: 'Tudo' },
]

export default function PeriodPicker({
  value,
  onChange,
}: {
  value: FinancePeriod
  onChange: (period: FinancePeriod) => void
}) {
  return (
    <div className="inline-flex rounded-lg border border-zinc-700 bg-zinc-900 p-0.5 text-sm">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          onClick={() => onChange(option.value)}
          className={`rounded-md px-3 py-1 transition ${
            value === option.value
              ? 'bg-purple-600 text-white'
              : 'text-zinc-400 hover:text-zinc-200'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
