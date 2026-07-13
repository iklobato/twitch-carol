import { useEffect, useState } from 'react'
import { apiGet } from '../api'
import type { FinanceOut } from '../types'

function usd(value: number): string {
  return value.toLocaleString('pt-BR', { style: 'currency', currency: 'USD' })
}

export default function FinanceSection({ streamId }: { streamId: number }) {
  const [finance, setFinance] = useState<FinanceOut | null>(null)

  useEffect(() => {
    apiGet<FinanceOut>(`/api/streams/${streamId}/finance`)
      .then(setFinance)
      .catch(() => setFinance(null))
  }, [streamId])

  if (finance === null || finance.money_events === 0) return null
  const maxTopic = Math.max(...finance.by_topic.map((topic) => topic.estimated_usd), 0.01)

  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Monetização</h3>
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-emerald-900/60 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">Arrecadado (estimado)</p>
          <p className="text-xl font-bold text-emerald-400">{usd(finance.estimated_usd)}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">Bits</p>
          <p className="text-xl font-bold">{finance.total_bits.toLocaleString('pt-BR')}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">Assinaturas</p>
          <p className="text-xl font-bold">{finance.total_subs.toLocaleString('pt-BR')}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">Subs presenteados</p>
          <p className="text-xl font-bold">{finance.total_gifts.toLocaleString('pt-BR')}</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {finance.top_contributors.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Quem mais contribuiu
            </p>
            <div className="space-y-1.5 text-sm">
              {finance.top_contributors.map((contributor, index) => (
                <div key={contributor.login} className="flex items-center justify-between">
                  <span>
                    <span className="mr-2 text-zinc-600">{index + 1}º</span>
                    <span className="text-purple-300">{contributor.login}</span>
                    <span className="ml-2 text-xs text-zinc-500">
                      {contributor.bits > 0 && `${contributor.bits} bits`}
                      {contributor.bits > 0 && contributor.subs > 0 && ' · '}
                      {contributor.subs > 0 && `${contributor.subs} sub(s)`}
                    </span>
                  </span>
                  <span className="font-semibold text-emerald-400">{usd(contributor.estimated_usd)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {finance.by_topic.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Assuntos que mais monetizaram
            </p>
            <div className="space-y-2 text-sm">
              {finance.by_topic.map((topic) => (
                <div key={topic.name} className="flex items-center gap-3">
                  <span className="w-40 shrink-0 truncate">{topic.name}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded bg-zinc-800">
                    <div
                      className="h-full rounded bg-emerald-500"
                      style={{ width: `${(topic.estimated_usd / maxTopic) * 100}%` }}
                    />
                  </div>
                  <span className="w-16 shrink-0 text-right text-emerald-400">
                    {usd(topic.estimated_usd)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      <p className="mt-2 text-[11px] text-zinc-600">
        Valores em dólar são estimativas da sua parte (Twitch não divulga o split exato).
      </p>
    </div>
  )
}
