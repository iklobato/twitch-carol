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

function dayHeading(iso: string): string {
  return new Date(iso).toLocaleDateString('pt-BR', {
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
    const key = new Date(stream.started_at).toDateString()
    const last = groups[groups.length - 1]
    if (last && last.key === key) last.streams.push(stream)
    else groups.push({ key, label: dayHeading(stream.started_at), streams: [stream] })
  }
  return groups
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
        <p className="mt-1 flex flex-wrap gap-x-4 text-xs text-zinc-500">
          <span>💬 {stream.messages.toLocaleString('pt-BR')} mensagens</span>
          <span>👤 {stream.chatters.toLocaleString('pt-BR')} chatters</span>
          <span>⚡ {stream.events.toLocaleString('pt-BR')} eventos</span>
          <span className={stream.followers > 0 ? 'text-emerald-400' : ''}>
            +{stream.followers.toLocaleString('pt-BR')} seguidores
          </span>
          <span>👁 pico {stream.peak_viewers.toLocaleString('pt-BR')} viewers</span>
        </p>
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

  useEffect(() => {
    apiGet<StreamListItem[]>('/api/streams').then(setStreams)
    apiGet<QueueItem[]>('/api/queue').then(setQueue)
    const timer = setInterval(() => {
      apiGet<StreamListItem[]>('/api/streams').then(setStreams)
      apiGet<QueueItem[]>('/api/queue').then(setQueue)
    }, 15000)
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
