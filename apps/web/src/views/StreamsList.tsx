import { useEffect, useState } from 'react'
import { apiGet, formatTime, STATUS_LABELS } from '../api'
import OverviewSection from '../components/OverviewSection'
import type { QueueItem, StreamListItem } from '../types'

function statusColor(status: string): string {
  if (status === 'ready') return 'bg-emerald-900 text-emerald-300'
  if (status === 'failed') return 'bg-red-900 text-red-300'
  if (status === 'capturing') return 'bg-purple-900 text-purple-300'
  return 'bg-amber-900 text-amber-300'
}

function dayHeading(day: string): string {
  // `day` is a plain YYYY-MM-DD (channel timezone); parse as local midnight so
  // the weekday/label lands on that calendar date in any browser.
  return new Date(`${day}T00:00:00`).toLocaleDateString('pt-BR', {
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

function MetricsLine({ metrics }: { metrics: DayMetrics }) {
  return (
    <p className="mt-1 flex flex-wrap gap-x-4 text-xs text-zinc-500">
      <span>💬 {metrics.messages.toLocaleString('pt-BR')} mensagens</span>
      <span>👤 {metrics.chatters.toLocaleString('pt-BR')} chatters</span>
      <span>⚡ {metrics.events.toLocaleString('pt-BR')} eventos</span>
      <span className={metrics.followers > 0 ? 'text-emerald-400' : ''}>
        +{metrics.followers.toLocaleString('pt-BR')} seguidores
      </span>
      <span>👁 pico {metrics.peak_viewers.toLocaleString('pt-BR')} viewers</span>
    </p>
  )
}

function StreamCard({ stream }: { stream: StreamListItem }) {
  return (
    <a
      href={`#/stream/${stream.id}`}
      className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900 p-4 hover:border-zinc-600"
    >
      <div>
        <p className="font-semibold">
          {stream.title ?? `Live #${stream.id}`}
          {stream.category && (
            <span className="ml-2 text-sm text-zinc-500">{stream.category}</span>
          )}
        </p>
        <p className="text-sm text-zinc-400">
          {formatTime(stream.started_at)}
          {stream.ended_at && ` – ${formatTime(stream.ended_at)}`}
        </p>
        <MetricsLine metrics={stream} />
        {stream.records.length > 0 && (
          <p className="mt-2 flex flex-wrap gap-1.5">
            {stream.records.map((record) => (
              <span
                key={record}
                className="rounded-full border border-amber-700 bg-amber-950/30 px-2 py-0.5 text-[11px] text-amber-300"
              >
                🏆 recorde de {record}
              </span>
            ))}
          </p>
        )}
      </div>
      <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusColor(stream.status)}`}>
        {STATUS_LABELS[stream.status] ?? stream.status}
      </span>
    </a>
  )
}

function QueueBanner({ items }: { items: QueueItem[] }) {
  if (items.length === 0) return null
  return (
    <div className="mb-4 rounded-lg border border-amber-800 bg-amber-950/40 p-4 text-sm">
      <p className="font-semibold text-amber-300">Processamento em andamento</p>
      {items.map((item) => (
        <p key={`${item.stream_id}-${item.job_type}`} className="text-amber-200/80">
          Live #{item.stream_id}: {item.job_type === 'transcribe' ? 'transcrição' : 'análise'}{' '}
          {item.status === 'running'
            ? 'rodando agora'
            : `na posição ${item.position} da fila` +
              (item.eta_seconds != null
                ? `, estimativa ~${Math.max(1, Math.round(item.eta_seconds / 60))} min`
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

  if (streams === null) return <p className="text-zinc-400">Carregando lives...</p>

  return (
    <div>
      <OverviewSection streams={streams} />
      <h2 className="mb-4 text-xl font-bold">Suas lives</h2>
      <QueueBanner items={queue} />
      {streams.length === 0 && (
        <p className="text-zinc-400">
          Nenhuma live capturada ainda. Transmita na Twitch e ela aparece aqui sozinha.
        </p>
      )}
      <div className="space-y-6">
        {groupByDay(streams).map((group) => (
          <div key={group.key}>
            <div className="mb-2 flex items-baseline gap-2">
              <h3 className="text-sm font-semibold capitalize text-zinc-300">{group.label}</h3>
              <span className="text-xs text-zinc-600">
                {group.streams.length} live{group.streams.length === 1 ? '' : 's'}
              </span>
            </div>
            {group.streams.length > 1 && (
              <div className="mb-2 rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-2">
                <p className="text-xs font-semibold text-zinc-400">Total do dia</p>
                <MetricsLine metrics={dayTotals(group.streams, dayChatters[group.key] ?? 0)} />
              </div>
            )}
            <div className="space-y-2">
              {group.streams.map((stream) => (
                <StreamCard key={stream.id} stream={stream} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
