import { useEffect, useState } from 'react'
import { apiGet, formatTime, statusLabel } from '../api'
import { fmtInt, fmtMoney, locale, t, type MessageKey } from '../i18n'
import OverviewSection from '../components/OverviewSection'
import type { FinanceOverview, QueueItem, StreamListItem } from '../types'

function statusColor(status: string): string {
  if (status === 'ready') return 'bg-money/15 text-money'
  if (status === 'failed') return 'bg-alert/15 text-alert'
  if (status === 'capturing') return 'bg-accent/20 text-accent-ink'
  return 'bg-amber-400/15 text-amber-300'
}

function dayHeading(day: string): string {
  // `day` is a plain YYYY-MM-DD (channel timezone); parse as local midnight so
  // the weekday/label lands on that calendar date in any browser.
  return new Date(`${day}T00:00:00`).toLocaleDateString(locale(), {
    weekday: 'long',
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  })
}

type DayGroup = { key: string; label: string; streams: StreamListItem[] }

export function groupByDay(streams: StreamListItem[]): DayGroup[] {
  const groups: DayGroup[] = []
  for (const stream of streams) {
    const last = groups[groups.length - 1]
    if (last && last.key === stream.day) last.streams.push(stream)
    else groups.push({ key: stream.day, label: dayHeading(stream.day), streams: [stream] })
  }
  return groups
}

type DayMetrics = {
  messages: number
  chatters: number
  events: number
  followers: number
  peak_viewers: number
}

// Messages/events/followers add up; peak is the day's highest, not a sum. Unique
// chatters come from the backend (uniqueChatters); summing per-live counts would
// double-count anyone active on more than one live.
export function dayTotals(streams: StreamListItem[], uniqueChatters: number): DayMetrics {
  return {
    messages: streams.reduce((n, s) => n + s.messages, 0),
    chatters: uniqueChatters,
    events: streams.reduce((n, s) => n + s.events, 0),
    followers: streams.reduce((n, s) => n + s.followers, 0),
    peak_viewers: Math.max(...streams.map((s) => s.peak_viewers)),
  }
}

/** A live with no money shows a dash: "US$ 0.00" reads like a measured loss. */
export function earnedLabel(usd: number | undefined): string {
  return usd !== undefined && usd > 0 ? fmtMoney(usd) : '—'
}

/** "3 lives" / "1 live", same shape in both catalogs. */
export function liveCount(n: number): string {
  return t(n === 1 ? 'streams.liveCount' : 'streams.liveCountPlural', { n })
}

function MetricsLine({ metrics }: { metrics: DayMetrics }) {
  return (
    <p className="mt-1 flex flex-wrap gap-x-4 text-xs text-ink-muted">
      <span>{t('metrics.messages', { n: fmtInt(metrics.messages) })}</span>
      <span>{t('metrics.chatters', { n: fmtInt(metrics.chatters) })}</span>
      <span>{t('metrics.events', { n: fmtInt(metrics.events) })}</span>
      <span className={metrics.followers > 0 ? 'text-money' : ''}>
        {t('metrics.followers', { n: fmtInt(metrics.followers) })}
      </span>
      <span>{t('metrics.peak', { n: fmtInt(metrics.peak_viewers) })}</span>
    </p>
  )
}

function StreamCard({ stream, earned }: { stream: StreamListItem; earned: number | undefined }) {
  return (
    <a
      href={`#/stream/${stream.id}`}
      className="flex items-center justify-between gap-4 rounded-2xl border border-line bg-panel p-4 hover:border-line-strong"
    >
      <div className="min-w-0">
        <p className="font-semibold">
          {stream.title ?? t('live.number', { id: stream.id })}
          {stream.category && (
            <span className="ml-2 text-sm font-normal text-ink-faint">{stream.category}</span>
          )}
        </p>
        <p className="text-sm text-ink-muted">
          {formatTime(stream.started_at)}
          {stream.ended_at && ` – ${formatTime(stream.ended_at)}`}
        </p>
        <MetricsLine metrics={stream} />
        {stream.records.length > 0 && (
          <p className="mt-2 flex flex-wrap gap-1.5">
            {stream.records.map((record) => (
              <span
                key={record}
                className="rounded-full border border-amber-400/40 px-2 py-0.5 text-xs text-amber-200"
              >
                {t('streams.record', { name: t(`record.${record}` as MessageKey) })}
              </span>
            ))}
          </p>
        )}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-2">
        <span className={`font-semibold ${earned ? 'text-money' : 'text-ink-faint'}`}>{earnedLabel(earned)}</span>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusColor(stream.status)}`}>
          {statusLabel(stream.status)}
        </span>
      </div>
    </a>
  )
}

function QueueBanner({ items }: { items: QueueItem[] }) {
  if (items.length === 0) return null
  return (
    <div className="mb-4 rounded-2xl border border-accent/30 bg-accent-soft p-4 text-sm">
      <p className="font-semibold text-accent-ink">{t('queue.title')}</p>
      {items.map((item) => (
        <p key={`${item.stream_id}-${item.job_type}`} className="text-ink-muted">
          {t('live.number', { id: item.stream_id })}:{' '}
          {item.job_type === 'transcribe' ? t('queue.transcription') : t('queue.analysis')}{' '}
          {item.status === 'running'
            ? t('queue.runningNow')
            : t('queue.positionInQueue', { n: item.position ?? '' }) +
              (item.eta_seconds != null
                ? t('queue.eta', { n: Math.max(1, Math.round(item.eta_seconds / 60)) })
                : '')}
        </p>
      ))}
    </div>
  )
}

export default function StreamsList() {
  const [streams, setStreams] = useState<StreamListItem[] | null>(null)
  const [queue, setQueue] = useState<QueueItem[]>([])
  const [dayChatters, setDayChatters] = useState<Record<string, number>>({})

  useEffect(() => {
    const load = () => {
      apiGet<StreamListItem[]>('/api/streams').then(setStreams)
      apiGet<QueueItem[]>('/api/queue').then(setQueue)
      apiGet<Record<string, number>>('/api/streams/day-chatters').then(setDayChatters)
    }
    load()
    const timer = setInterval(load, 15000)
    return () => clearInterval(timer)
  }, [])

  // Money per live only changes when a live is analyzed: once per visit is enough.
  const [earnedByStream, setEarnedByStream] = useState<Map<number, number>>(new Map())
  useEffect(() => {
    apiGet<FinanceOverview>('/api/finance?period=all')
      .then((finance) =>
        setEarnedByStream(new Map(finance.by_stream.map((row) => [row.stream_id, row.estimated_usd]))),
      )
      .catch(() => setEarnedByStream(new Map()))
  }, [])

  if (streams === null) return <p className="text-ink-muted">{t('streams.loading')}</p>

  return (
    <div>
      <OverviewSection streams={streams} />
      <h2 className="mb-4 font-display text-xl font-semibold">{t('streams.title')}</h2>
      <QueueBanner items={queue} />
      {streams.length === 0 && <p className="text-ink-muted">{t('streams.empty')}</p>}
      <div className="space-y-6">
        {groupByDay(streams).map((group) => (
          <div key={group.key}>
            <div className="mb-2 flex items-baseline gap-2">
              <h3 className="text-sm font-semibold capitalize">{group.label}</h3>
              <span className="text-xs text-ink-faint">{liveCount(group.streams.length)}</span>
            </div>
            {group.streams.length > 1 && (
              <div className="mb-2 rounded-2xl border border-line px-4 py-2">
                <p className="text-xs font-semibold text-ink-muted">{t('streams.dayTotal')}</p>
                <MetricsLine metrics={dayTotals(group.streams, dayChatters[group.key] ?? 0)} />
              </div>
            )}
            <div className="space-y-2">
              {group.streams.map((stream) => (
                <StreamCard key={stream.id} stream={stream} earned={earnedByStream.get(stream.id)} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
