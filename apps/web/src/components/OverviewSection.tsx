import { useEffect, useState } from 'react'
import { apiGet, formatDate } from '../api'
import PeriodPicker from './PeriodPicker'
import type {
  ChannelOverview,
  FinanceOverview,
  FinancePeriod,
  FollowersOverview,
  NumberComparison,
  StreamListItem,
  StreamReport,
} from '../types'

function usd(value: number): string {
  return value.toLocaleString('pt-BR', { style: 'currency', currency: 'USD' })
}

// Which single "needs attention" item to surface, by priority. Pure so it can
// be unit-tested. Queue is intentionally excluded (StreamsList already shows a
// QueueBanner), so this focuses on risk, goals, then AI advice.
export type Highlight = { tone: 'risk' | 'goal' | 'reco'; text: string } | null

const SUSPICIOUS_ALERT_MIN = 10
const GOAL_NEAR_PCT = 80

export function pickHighlight(
  followers: FollowersOverview | null,
  channel: ChannelOverview | null,
): Highlight {
  if (followers) {
    if (followers.signals.velocity.some((day) => day.is_spike)) {
      return {
        tone: 'risk',
        text: 'Pico anômalo de follows recente. Veja "De onde vêm e o que é real".',
      }
    }
    if (followers.signals.suspicious_total >= SUSPICIOUS_ALERT_MIN) {
      return {
        tone: 'risk',
        text: `${followers.signals.suspicious_total} seguidores com sinais de fake. Revise em Meus seguidores.`,
      }
    }
  }
  if (channel) {
    const near = channel.community.goals.find(
      (goal) => goal.pct >= GOAL_NEAR_PCT && goal.current_amount < goal.target_amount,
    )
    if (near) {
      const remaining = near.target_amount - near.current_amount
      return {
        tone: 'goal',
        text: `Faltam ${remaining.toLocaleString('pt-BR')} para a meta "${
          near.description ?? near.goal_type
        }" (${near.pct}%).`,
      }
    }
    if (channel.recommendations.length > 0) {
      return { tone: 'reco', text: channel.recommendations[0].content }
    }
  }
  return null
}

function Delta({ pct }: { pct: number | null }) {
  if (pct === null) return null
  const up = pct >= 0
  return (
    <span className={`text-xs font-semibold ${up ? 'text-emerald-400' : 'text-red-400'}`}>
      {up ? '▲' : '▼'} {Math.abs(pct)}%
    </span>
  )
}

function Kpi({
  label,
  value,
  sub,
}: {
  label: string
  value: string
  sub?: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="text-xl font-bold">{value}</p>
      {sub && <div className="mt-0.5 text-xs text-zinc-500">{sub}</div>}
    </div>
  )
}

function mean(values: number[]): number {
  if (values.length === 0) return 0
  return values.reduce((sum, v) => sum + v, 0) / values.length
}

function KpiStrip({
  channel,
  followers,
  finance,
  period,
}: {
  channel: ChannelOverview | null
  followers: FollowersOverview | null
  finance: FinanceOverview | null
  period: FinancePeriod
}) {
  const avgPeak = channel ? Math.round(mean(channel.growth.map((g) => g.peak_viewers))) : 0
  const periodLabel = period === 'all' ? 'tudo' : period
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
      <Kpi
        label="Seguidores"
        value={followers ? followers.kpis.total.toLocaleString('pt-BR') : '–'}
        sub={
          followers && followers.kpis.new_30d > 0 ? (
            <span className="text-emerald-400">▲ +{followers.kpis.new_30d} · 30d</span>
          ) : (
            '30d'
          )
        }
      />
      <Kpi
        label={`Arrecadado (${periodLabel})`}
        value={finance ? usd(finance.estimated_usd) : '–'}
        sub={finance ? <Delta pct={finance.delta_pct} /> : undefined}
      />
      <Kpi
        label="Assinantes"
        value={channel ? channel.subscribers.total.toLocaleString('pt-BR') : '–'}
        sub={channel ? `churn: ${channel.subscribers.subs_ended}` : undefined}
      />
      <Kpi label="Pico médio" value={channel ? avgPeak.toLocaleString('pt-BR') : '–'} />
      <Kpi
        label="Lives"
        value={channel ? channel.total_streams.toLocaleString('pt-BR') : '–'}
      />
    </div>
  )
}

function StatWithDelta({ label, comparison }: { label: string; comparison?: NumberComparison }) {
  if (!comparison) return null
  return (
    <span>
      {comparison.value.toLocaleString('pt-BR')} {label} <Delta pct={comparison.delta_pct} />
    </span>
  )
}

function LastLiveCard({
  stream,
  report,
}: {
  stream: StreamListItem | null
  report: StreamReport | null
}) {
  if (!stream) return null
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Sua última live
      </p>
      <p className="font-semibold">
        {stream.title ?? `Live #${stream.id}`}
        {stream.category && <span className="ml-2 text-sm text-zinc-500">{stream.category}</span>}
      </p>
      <p className="text-xs text-zinc-500">{formatDate(stream.started_at)}</p>
      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-400">
        {report ? (
          <>
            <StatWithDelta label="mensagens" comparison={report.numbers.messages} />
            <StatWithDelta label="chatters" comparison={report.numbers.chatters} />
            <StatWithDelta label="pico" comparison={report.numbers.peak_viewers} />
          </>
        ) : (
          <>
            <span>💬 {stream.messages.toLocaleString('pt-BR')}</span>
            <span>👤 {stream.chatters.toLocaleString('pt-BR')}</span>
            <span>👁 {stream.peak_viewers.toLocaleString('pt-BR')}</span>
          </>
        )}
        <span className={stream.followers > 0 ? 'text-emerald-400' : ''}>
          +{stream.followers.toLocaleString('pt-BR')} seguidores
        </span>
      </p>
      <a
        href={`#/stream/${stream.id}`}
        className="mt-2 inline-block text-xs text-purple-300 hover:text-purple-200"
      >
        ver relatório →
      </a>
    </div>
  )
}

const HIGHLIGHT_TONE: Record<'risk' | 'goal' | 'reco', string> = {
  risk: 'border-red-900/60 bg-red-950/20',
  goal: 'border-emerald-900/60 bg-emerald-950/20',
  reco: 'border-purple-900/60 bg-purple-950/20',
}

const HIGHLIGHT_ICON: Record<'risk' | 'goal' | 'reco', string> = {
  risk: '⚠️',
  goal: '🎯',
  reco: '💡',
}

function ActionableHighlight({ highlight }: { highlight: Highlight }) {
  if (!highlight) return null
  return (
    <div className={`rounded-lg border p-4 ${HIGHLIGHT_TONE[highlight.tone]}`}>
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Precisa de atenção
      </p>
      <p className="text-sm">
        {HIGHLIGHT_ICON[highlight.tone]} {highlight.text}
      </p>
    </div>
  )
}

function mostRecentReady(streams: StreamListItem[] | null): StreamListItem | null {
  if (!streams) return null
  const ready = streams.filter((s) => s.status === 'ready')
  if (ready.length === 0) return null
  return ready.reduce((latest, s) => (s.started_at > latest.started_at ? s : latest))
}

export default function OverviewSection({ streams }: { streams: StreamListItem[] | null }) {
  const [period, setPeriod] = useState<FinancePeriod>('30d')
  const [channel, setChannel] = useState<ChannelOverview | null>(null)
  const [followers, setFollowers] = useState<FollowersOverview | null>(null)
  const [finance, setFinance] = useState<FinanceOverview | null>(null)
  const [report, setReport] = useState<StreamReport | null>(null)

  // Account-level blocks: fetch once (they don't need the 15s stream poll).
  useEffect(() => {
    apiGet<ChannelOverview>('/api/channel').then(setChannel).catch(() => setChannel(null))
    apiGet<FollowersOverview>('/api/followers').then(setFollowers).catch(() => setFollowers(null))
  }, [])

  // Money KPI follows the period selector.
  useEffect(() => {
    apiGet<FinanceOverview>(`/api/finance?period=${period}`)
      .then(setFinance)
      .catch(() => setFinance(null))
  }, [period])

  const lastLive = mostRecentReady(streams)
  useEffect(() => {
    if (!lastLive) return
    apiGet<StreamReport>(`/api/streams/${lastLive.id}`)
      .then(setReport)
      .catch(() => setReport(null))
  }, [lastLive?.id])

  const highlight = pickHighlight(followers, channel)
  // Nothing to show yet (fresh account, still loading): render nothing.
  if (!channel && !followers && !finance && !lastLive) return null

  return (
    <div className="mb-8">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-bold">Visão geral</h2>
        <PeriodPicker value={period} onChange={setPeriod} />
      </div>
      <KpiStrip channel={channel} followers={followers} finance={finance} period={period} />
      {(lastLive || highlight) && (
        <div className="grid gap-4 md:grid-cols-2">
          <LastLiveCard stream={lastLive} report={report} />
          <ActionableHighlight highlight={highlight} />
        </div>
      )}
    </div>
  )
}
