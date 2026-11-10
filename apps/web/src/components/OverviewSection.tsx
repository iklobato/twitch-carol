import { useEffect, useState, type ReactNode } from 'react'
import { apiGet, formatDate } from '../api'
import { fmtInt, fmtMoney, t } from '../i18n'
import PeriodPicker from './PeriodPicker'
import type {
  ChannelOverview,
  FinanceOverview,
  FinancePeriod,
  FollowersOverview,
  NumberComparison,
  Recommendation,
  StreamListItem,
  StreamReport,
  Timeline,
  TimelinePoint,
} from '../types'

// Everything that needs the streamer now, in priority order. Pure so it can be
// unit-tested. The queue is left out (StreamsList shows it) and the AI advice
// has its own card above the numbers.
export type Attention = { tone: 'risk' | 'goal'; text: string; href: string }

const SUSPICIOUS_ALERT_MIN = 10
const GOAL_NEAR_PCT = 80

export function pickAttention(
  followers: FollowersOverview | null,
  channel: ChannelOverview | null,
): Attention[] {
  const items: Attention[] = []
  if (followers) {
    if (followers.signals.velocity.some((day) => day.is_spike)) {
      items.push({ tone: 'risk', text: t('overview.highlight.spike'), href: '#/audience' })
    }
    if (followers.signals.suspicious_total >= SUSPICIOUS_ALERT_MIN) {
      items.push({
        tone: 'risk',
        text: t('overview.highlight.suspicious', { n: followers.signals.suspicious_total }),
        href: '#/audience',
      })
    }
  }
  if (channel) {
    for (const goal of channel.community.goals) {
      if (goal.pct >= GOAL_NEAR_PCT && goal.current_amount < goal.target_amount) {
        items.push({
          tone: 'goal',
          text: t('overview.highlight.goal', {
            remaining: fmtInt(goal.target_amount - goal.current_amount),
            goal: goal.description ?? goal.goal_type,
            pct: goal.pct,
          }),
          href: '#/money',
        })
      }
    }
  }
  return items
}

/** SVG path of the chat pace across the whole live, scaled into width x height. */
export function chatPath(points: TimelinePoint[], width: number, height: number): string {
  if (points.length < 2) return ''
  const max = Math.max(...points.map((point) => point.value), 1)
  const step = width / (points.length - 1)
  return points
    .map((point, index) => {
      const x = (index * step).toFixed(1)
      const y = (height - (point.value / max) * height).toFixed(1)
      return `${index === 0 ? 'M' : 'L'}${x} ${y}`
    })
    .join(' ')
}

function Delta({ pct }: { pct: number | null }) {
  if (pct === null) return null
  const up = pct >= 0
  return (
    <span className={`text-xs font-semibold ${up ? 'text-money' : 'text-alert'}`}>
      {up ? '▲' : '▼'} {Math.abs(pct)}%
    </span>
  )
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-line bg-panel p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-faint">{label}</p>
      <p className="mt-1 font-display text-2xl font-semibold">{value}</p>
      {sub && <div className="mt-0.5 text-xs text-ink-muted">{sub}</div>}
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
  const periodLabel = period === 'all' ? t('overview.period.all') : period
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      <Kpi
        label={t('followers.kpi.total')}
        value={followers ? fmtInt(followers.kpis.total) : '–'}
        sub={
          followers && followers.kpis.new_30d > 0 ? (
            <span className="text-money">▲ +{followers.kpis.new_30d} · 30d</span>
          ) : (
            '30d'
          )
        }
      />
      <Kpi
        label={t('overview.kpi.earned', { period: periodLabel })}
        value={finance ? fmtMoney(finance.estimated_usd) : '–'}
        sub={finance ? <Delta pct={finance.delta_pct} /> : undefined}
      />
      <Kpi
        label={t('subs.active')}
        value={channel ? fmtInt(channel.subscribers.total) : '–'}
        sub={channel ? t('overview.kpi.churn', { n: channel.subscribers.subs_ended }) : undefined}
      />
      <Kpi label={t('overview.kpi.avgPeak')} value={channel ? fmtInt(avgPeak) : '–'} />
      <Kpi
        label={t('channel.stat.streams')}
        value={channel ? fmtInt(channel.total_streams) : '–'}
      />
    </div>
  )
}

function NextStepCard({ recommendation }: { recommendation: Recommendation | undefined }) {
  if (!recommendation) return null
  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-accent/30 bg-accent-soft p-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-accent/20 px-2.5 py-1 text-xs font-semibold text-accent-ink">
          {t('overview.nextStep')}
        </span>
        <span className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
          {t('overview.nextStepNote')}
        </span>
      </div>
      <p className="max-w-3xl text-lg font-medium leading-snug">{recommendation.content}</p>
      {recommendation.facts.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {recommendation.facts.map((fact) => (
            <span
              key={fact}
              className="rounded-lg border border-line-strong bg-panel px-2.5 py-1 text-xs text-ink-muted"
            >
              {fact}
            </span>
          ))}
        </div>
      )}
    </section>
  )
}

const TONE_DOT: Record<Attention['tone'], string> = {
  risk: 'bg-alert',
  goal: 'bg-accent',
}

function NeedsAttention({ items }: { items: Attention[] }) {
  if (items.length === 0) return null
  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-line bg-panel p-5">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg font-semibold">{t('overview.needsAttention')}</h3>
        <span className="rounded-full bg-alert/15 px-2.5 py-0.5 text-xs font-semibold text-alert">
          {items.length}
        </span>
      </div>
      {items.map((item) => (
        <a
          key={item.text}
          href={item.href}
          className="flex min-h-11 items-start gap-3 rounded-xl bg-panel-raised p-3 text-sm hover:bg-line"
        >
          <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${TONE_DOT[item.tone]}`} />
          {item.text}
        </a>
      ))}
    </section>
  )
}

function StatWithDelta({ label, comparison }: { label: string; comparison?: NumberComparison }) {
  if (!comparison) return null
  return (
    <span>
      <b className="text-ink">{fmtInt(comparison.value)}</b> {label} <Delta pct={comparison.delta_pct} />
    </span>
  )
}

const SPARK_WIDTH = 400
const SPARK_HEIGHT = 64

function LastLiveCard({
  stream,
  report,
  timeline,
}: {
  stream: StreamListItem | null
  report: StreamReport | null
  timeline: Timeline | null
}) {
  if (!stream) return null
  const path = timeline ? chatPath(timeline.chat, SPARK_WIDTH, SPARK_HEIGHT) : ''
  return (
    <a
      href={`#/stream/${stream.id}`}
      className="flex flex-col gap-3 rounded-2xl border border-line bg-panel p-5 hover:border-line-strong"
    >
      <h3 className="font-display text-lg font-semibold">{t('overview.lastLive')}</h3>
      <div>
        <p className="font-semibold">{stream.title ?? t('live.number', { id: stream.id })}</p>
        <p className="text-sm text-ink-muted">
          {formatDate(stream.started_at)}
          {stream.category && ` · ${stream.category}`}
        </p>
      </div>
      {path && (
        <svg
          viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
          preserveAspectRatio="none"
          className="h-16 w-full"
          role="img"
          aria-label={t('chart.messagesPerMin')}
        >
          <path
            d={`${path} L${SPARK_WIDTH} ${SPARK_HEIGHT} L0 ${SPARK_HEIGHT} Z`}
            fill="var(--color-accent-soft)"
          />
          <path d={path} fill="none" stroke="var(--color-accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        </svg>
      )}
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-muted">
        {report ? (
          <>
            <StatWithDelta label={t('overview.stat.messages')} comparison={report.numbers.messages} />
            <StatWithDelta label={t('overview.stat.chatters')} comparison={report.numbers.chatters} />
            <StatWithDelta label={t('overview.stat.peak')} comparison={report.numbers.peak_viewers} />
          </>
        ) : (
          <>
            <span>{t('metrics.messages', { n: fmtInt(stream.messages) })}</span>
            <span>{t('metrics.chatters', { n: fmtInt(stream.chatters) })}</span>
            <span>{t('metrics.peak', { n: fmtInt(stream.peak_viewers) })}</span>
          </>
        )}
        <span className={stream.followers > 0 ? 'text-money' : ''}>
          {t('metrics.followers', { n: fmtInt(stream.followers) })}
        </span>
      </p>
      <span className="text-sm text-accent-ink">{t('overview.seeReport')}</span>
    </a>
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
  const [timeline, setTimeline] = useState<Timeline | null>(null)

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
    apiGet<Timeline>(`/api/streams/${lastLive.id}/timeline`)
      .then(setTimeline)
      .catch(() => setTimeline(null))
  }, [lastLive?.id])

  const attention = pickAttention(followers, channel)
  // Nothing to show yet (fresh account, still loading): render nothing.
  if (!channel && !followers && !finance && !lastLive) return null

  return (
    <div className="mb-10 flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="font-display text-3xl font-semibold">{t('overview.title')}</h1>
        <PeriodPicker value={period} onChange={setPeriod} />
      </div>
      <NextStepCard recommendation={channel?.recommendations[0]} />
      <KpiStrip channel={channel} followers={followers} finance={finance} period={period} />
      {(lastLive || attention.length > 0) && (
        <div className={`grid gap-4 ${lastLive && attention.length > 0 ? 'md:grid-cols-2' : ''}`}>
          <NeedsAttention items={attention} />
          <LastLiveCard stream={lastLive} report={report} timeline={timeline} />
        </div>
      )}
    </div>
  )
}
