import { startCheckout } from '../api'

export default function UpgradeBanner({ trialUsed }: { trialUsed: boolean }) {
  const headline = trialUsed
    ? 'Você já usou sua live grátis.'
    : 'Sua primeira live é grátis.'
  const detail = trialUsed
    ? 'Assine o PRO para analisar todas as suas próximas lives.'
    : 'Assine o PRO para analisar todas as lives, não só a primeira.'

  return (
    <div className="mb-6 flex flex-col gap-3 rounded-xl border border-purple-700 bg-purple-950/40 p-5 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="font-semibold text-purple-100">{headline}</p>
        <p className="text-sm text-purple-300">{detail}</p>
      </div>
      <button
        onClick={startCheckout}
        className="shrink-0 rounded-lg bg-purple-600 px-5 py-2.5 font-semibold hover:bg-purple-500"
      >
        Assinar PRO — R$49,90/mês
      </button>
    </div>
  )
}
