import { useEffect, useState } from 'react'
import { apiGet, formatDate } from '../api'
import PeriodPicker from '../components/PeriodPicker'
import type { FinanceOverview, FinancePeriod } from '../types'

function usd(value: number): string {
  return value.toLocaleString('pt-BR', { style: 'currency', currency: 'USD' })
}

const PERIOD_LABELS: Record<FinancePeriod, string> = {
  '30d': 'nos últimos 30 dias',
  '90d': 'nos últimos 90 dias',
  all: 'em todas as lives',
}

function Delta({ pct }: { pct: number | null }) {
  if (pct === null) return null
  const up = pct >= 0
  return (
    <span className={`text-sm font-semibold ${up ? 'text-emerald-400' : 'text-red-400'}`}>
      {up ? '▲' : '▼'} {Math.abs(pct)}%
      <span className="ml-1 text-xs font-normal text-zinc-500">vs. período anterior</span>
    </span>
  )
}

function KpiRow({ finance }: { finance: FinanceOverview }) {
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
      <div className="rounded-lg border border-emerald-900/60 bg-zinc-900 p-3">
        <p className="text-xs text-zinc-500">Arrecadado (estimado)</p>
        <p className="text-xl font-bold text-emerald-400">{usd(finance.estimated_usd)}</p>
        <Delta pct={finance.delta_pct} />
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
  )
}

function RevenueByStream({ finance }: { finance: FinanceOverview }) {
  if (finance.by_stream.length === 0) return null
  const max = Math.max(...finance.by_stream.map((row) => row.estimated_usd), 0.01)
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Receita por live</h3>
      <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm">
        {finance.by_stream.map((row) => (
          <a
            key={row.stream_id}
            href={`#/stream/${row.stream_id}`}
            className="flex items-center gap-3 hover:text-purple-300"
          >
            <span className="w-24 shrink-0 text-xs text-zinc-500">
              {formatDate(row.started_at)}
            </span>
            <span className="min-w-0 flex-1 truncate">{row.title ?? `Live #${row.stream_id}`}</span>
            <div className="hidden h-2 w-40 overflow-hidden rounded bg-zinc-800 md:block">
              <div
                className="h-full rounded bg-emerald-500"
                style={{ width: `${(row.estimated_usd / max) * 100}%` }}
              />
            </div>
            <span className="w-16 shrink-0 text-right text-emerald-400">
              {usd(row.estimated_usd)}
            </span>
          </a>
        ))}
      </div>
    </div>
  )
}

function TopContributors({ finance }: { finance: FinanceOverview }) {
  if (finance.top_contributors.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Quem mais contribuiu</h3>
      <div className="space-y-1.5 rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm">
        {finance.top_contributors.map((contributor, index) => (
          <div key={contributor.login} className="flex items-center justify-between">
            <span>
              <span className="mr-2 text-zinc-600">{index + 1}º</span>
              <span className="text-purple-300">{contributor.login}</span>
              <span className="ml-2 text-xs text-zinc-500">
                em {contributor.streams} live{contributor.streams > 1 ? 's' : ''}
              </span>
            </span>
            <span className="font-semibold text-emerald-400">
              {usd(contributor.estimated_usd)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ContentRevenue({ finance }: { finance: FinanceOverview }) {
  if (finance.by_content.length === 0) return null
  const maxPerHour = Math.max(...finance.by_content.map((b) => b.usd_per_hour), 0.01)
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">Conteúdo que converte</h3>
      <p className="mb-3 text-sm text-zinc-500">
        Receita por categoria e por hora transmitida. Faça mais do que rende mais por hora.
      </p>
      <div className="space-y-2 text-sm">
        {finance.by_content.map((bucket) => (
          <div key={bucket.category} className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
            <div className="mb-1 flex items-center justify-between">
              <span className="font-semibold">{bucket.category}</span>
              <span className="text-emerald-400">
                {usd(bucket.usd_per_hour)}
                <span className="text-xs text-zinc-500">/h</span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded bg-zinc-800">
              <div
                className="h-full rounded bg-emerald-500"
                style={{ width: `${(bucket.usd_per_hour / maxPerHour) * 100}%` }}
              />
            </div>
            <div className="mt-1 flex justify-between text-xs text-zinc-500">
              <span>
                {bucket.streams} live{bucket.streams > 1 ? 's' : ''} · pico médio{' '}
                {bucket.avg_peak_viewers.toLocaleString('pt-BR')}
              </span>
              <span>{usd(bucket.estimated_usd)} no total</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Engagement({ finance }: { finance: FinanceOverview }) {
  const { hype_train, top_rewards, ads } = finance.engagement
  if (hype_train.count === 0 && top_rewards.length === 0 && ads.breaks === 0) return null
  const maxRedemptions = Math.max(...top_rewards.map((r) => r.redemptions), 1)
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Engajamento que gera receita</h3>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Hype Trains
          </p>
          {hype_train.count > 0 ? (
            <div className="space-y-1 text-sm">
              <p className="text-2xl font-bold text-purple-300">{hype_train.count}</p>
              <p className="text-zinc-400">Melhor nível: {hype_train.best_level}</p>
              <p className="text-zinc-500">
                {hype_train.total_contributed.toLocaleString('pt-BR')} em contribuições
              </p>
            </div>
          ) : (
            <p className="text-sm text-zinc-600">Nenhum hype train no período.</p>
          )}
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Recompensas mais resgatadas
          </p>
          {top_rewards.length > 0 ? (
            <div className="space-y-1.5 text-sm">
              {top_rewards.map((reward) => (
                <div key={reward.title} className="flex items-center gap-2">
                  <span className="w-28 shrink-0 truncate" title={reward.title}>
                    {reward.title}
                  </span>
                  <div className="h-2 flex-1 overflow-hidden rounded bg-zinc-800">
                    <div
                      className="h-full rounded bg-purple-500"
                      style={{ width: `${(reward.redemptions / maxRedemptions) * 100}%` }}
                    />
                  </div>
                  <span className="w-8 shrink-0 text-right text-zinc-400">{reward.redemptions}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-zinc-600">Nenhum resgate de pontos no período.</p>
          )}
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Anúncios
          </p>
          {ads.breaks > 0 ? (
            <div className="space-y-1 text-sm">
              <p className="text-zinc-400">
                {ads.breaks} break{ads.breaks > 1 ? 's' : ''} ·{' '}
                {Math.round(ads.total_seconds / 60)}min de ads
              </p>
              {ads.avg_viewer_change_pct !== null && (
                <p className={ads.avg_viewer_change_pct < 0 ? 'text-red-400' : 'text-emerald-400'}>
                  {ads.avg_viewer_change_pct > 0 ? '+' : ''}
                  {ads.avg_viewer_change_pct}% de viewers ao redor dos ads
                </p>
              )}
              <p className="text-[11px] text-zinc-600">
                A Twitch não expõe a receita de anúncios, só o impacto na audiência.
              </p>
            </div>
          ) : (
            <p className="text-sm text-zinc-600">Nenhum ad break no período.</p>
          )}
        </div>
      </div>
    </div>
  )
}

const TIER_LABELS: Record<string, string> = {
  '1000': 'Tier 1',
  '2000': 'Tier 2',
  '3000': 'Tier 3',
}

function Subscribers({ finance }: { finance: FinanceOverview }) {
  const { total, tiers, gifted_pct, subs_ended, top_bits } = finance.subscribers
  if (total === 0 && top_bits.length === 0 && subs_ended === 0) return null
  return (
    <div className="mb-6">
      <div className="mb-3 flex items-baseline gap-2">
        <h3 className="text-lg font-bold">Assinantes e bits</h3>
        <span className="rounded-full border border-zinc-700 px-2 py-0.5 text-[10px] text-zinc-400">
          estado atual
        </span>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Assinantes ativos
          </p>
          <p className="text-2xl font-bold text-purple-300">{total.toLocaleString('pt-BR')}</p>
          <div className="mt-2 space-y-1 text-sm">
            {tiers.map((t) => (
              <div key={t.tier} className="flex justify-between text-zinc-400">
                <span>{TIER_LABELS[t.tier] ?? t.tier}</span>
                <span>{t.count}</span>
              </div>
            ))}
            <div className="flex justify-between text-zinc-500">
              <span>Presenteados</span>
              <span>{gifted_pct}%</span>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Churn</p>
          <p className="text-2xl font-bold text-red-400">{subs_ended}</p>
          <p className="text-xs text-zinc-500">
            assinaturas encerradas nas lives do período
          </p>
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Top bits (todos os tempos)
          </p>
          {top_bits.length > 0 ? (
            <div className="space-y-1 text-sm">
              {top_bits.slice(0, 5).map((leader, index) => (
                <div key={leader.login} className="flex justify-between">
                  <span>
                    <span className="mr-2 text-zinc-600">{index + 1}º</span>
                    <span className="text-purple-300">{leader.login}</span>
                  </span>
                  <span className="text-zinc-400">{leader.score.toLocaleString('pt-BR')}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-zinc-600">Sem leaderboard (requer afiliação).</p>
          )}
        </div>
      </div>
    </div>
  )
}

function Goals({ finance }: { finance: FinanceOverview }) {
  if (finance.goals.length === 0) return null
  return (
    <div className="mb-6">
      <div className="mb-3 flex items-baseline gap-2">
        <h3 className="text-lg font-bold">Metas</h3>
        <span className="rounded-full border border-zinc-700 px-2 py-0.5 text-[10px] text-zinc-400">
          estado atual
        </span>
      </div>
      <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm">
        {finance.goals.map((goal) => {
          const reached = goal.current_amount >= goal.target_amount
          return (
            <div key={goal.goal_type + goal.description}>
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="font-medium">{goal.description ?? goal.goal_type}</span>
                <span className="tabular-nums text-zinc-400">
                  {goal.current_amount.toLocaleString('pt-BR')}/
                  {goal.target_amount.toLocaleString('pt-BR')}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded bg-zinc-800">
                <div
                  className={`h-full rounded ${reached ? 'bg-emerald-500' : 'bg-purple-500'}`}
                  style={{ width: `${Math.min(goal.pct, 100)}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                {goal.pct}%{reached && <span className="ml-2 text-emerald-400">✓ alcançada</span>}
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Recommendations({ finance }: { finance: FinanceOverview }) {
  if (finance.recommendations.length === 0) return null
  return (
    <div className="mb-6 rounded-lg border border-purple-900/60 bg-purple-950/20 p-4">
      <h3 className="mb-1 text-lg font-bold">Como ganhar mais (IA)</h3>
      <p className="mb-3 text-xs text-zinc-500">
        Recomendações geradas a partir dos seus números, atualizadas quando uma live é analisada.
      </p>
      <div className="space-y-3">
        {finance.recommendations.map((rec, index) => (
          <div key={index} className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
            <p className="text-sm">{rec.content}</p>
            {rec.facts.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-xs text-zinc-500">
                {rec.facts.map((fact, i) => (
                  <li key={i}>{fact.replace(/^\[\d+\]\s*/, '↳ ')}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function FinanceView() {
  const [period, setPeriod] = useState<FinancePeriod>('30d')
  const [finance, setFinance] = useState<FinanceOverview | null>(null)

  useEffect(() => {
    setFinance(null)
    apiGet<FinanceOverview>(`/api/finance?period=${period}`)
      .then(setFinance)
      .catch(() => setFinance(null))
  }, [period])

  const nothingYet =
    finance !== null &&
    finance.money_events === 0 &&
    finance.engagement.hype_train.count === 0 &&
    finance.engagement.ads.breaks === 0 &&
    finance.subscribers.total === 0 &&
    finance.goals.length === 0

  return (
    <div>
      <a href="#/" className="text-sm text-zinc-400 hover:text-zinc-200">
        ← voltar
      </a>
      <div className="mb-4 mt-2 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-bold">Financeiro</h2>
        <PeriodPicker value={period} onChange={setPeriod} />
      </div>

      {finance === null ? (
        <p className="text-zinc-400">Carregando o financeiro...</p>
      ) : nothingYet ? (
        <p className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-400">
          Nada monetizado {PERIOD_LABELS[period]}. Bits, assinaturas, hype trains e metas aparecem
          aqui quando seu canal monetizar (requer parceria/afiliação na Twitch).
        </p>
      ) : (
        <>
          <p className="mb-4 text-sm text-zinc-500">
            Tudo que você recebeu {PERIOD_LABELS[period]}. Valores em dólar são estimativas da sua
            parte: a Twitch não divulga o repasse exato.
          </p>
          <KpiRow finance={finance} />
          <RevenueByStream finance={finance} />
          <TopContributors finance={finance} />
          <ContentRevenue finance={finance} />
          <Engagement finance={finance} />
          <Subscribers finance={finance} />
          <Goals finance={finance} />
          <Recommendations finance={finance} />
        </>
      )}
    </div>
  )
}
