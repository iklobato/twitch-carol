import {
  CategoryScale,
  Chart,
  Filler,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
} from 'chart.js'
import { useEffect, useRef, useState } from 'react'
import { EVENT_LABELS, apiGet, formatTime } from '../api'
import type { CommunityOut, EventMarker } from '../types'

Chart.register(
  LineController,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Filler,
  Tooltip,
  Legend,
)

function sentimentLabel(score: number): { text: string; color: string } {
  if (score > 0.15) return { text: 'positivo', color: 'text-emerald-400' }
  if (score < -0.15) return { text: 'negativo', color: 'text-red-400' }
  return { text: 'neutro', color: 'text-zinc-400' }
}

function SentimentGauge({ score }: { score: number }) {
  // -1..+1 mapped to 0..100%; center line at 50%
  const position = ((score + 1) / 2) * 100
  const color = score > 0.15 ? '#34d399' : score < -0.15 ? '#f87171' : '#a1a1aa'
  return (
    <div>
      <div className="relative h-2 rounded-full bg-gradient-to-r from-red-500/40 via-zinc-600/40 to-emerald-500/40">
        <div className="absolute left-1/2 top-0 h-2 w-px bg-zinc-500" />
        <div
          className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-zinc-900"
          style={{ left: `${position}%`, backgroundColor: color }}
        />
      </div>
      <div className="mt-0.5 flex justify-between text-[10px] text-zinc-600">
        <span>negativo</span>
        <span>neutro</span>
        <span>positivo</span>
      </div>
    </div>
  )
}

function SentimentChart({
  community,
  events,
}: {
  community: CommunityOut
  events: EventMarker[]
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const chartRef = useRef<Chart | null>(null)

  useEffect(() => {
    if (!canvasRef.current || community.sentiment_timeline.length === 0) return
    chartRef.current?.destroy()
    const points = community.sentiment_timeline
    // snap each event to its nearest 30s sentiment bucket, keep the labels
    const times = points.map((point) => new Date(point.t).getTime())
    const eventsByIndex = new Map<number, string[]>()
    for (const event of events) {
      const t = new Date(event.t).getTime()
      let nearest = 0
      let bestGap = Infinity
      times.forEach((pointTime, index) => {
        const gap = Math.abs(pointTime - t)
        if (gap < bestGap) {
          bestGap = gap
          nearest = index
        }
      })
      const name = EVENT_LABELS[event.type] ?? event.type
      const text = event.amount != null ? `${name} (${event.amount})` : name
      eventsByIndex.set(nearest, [...(eventsByIndex.get(nearest) ?? []), text])
    }

    chartRef.current = new Chart(canvasRef.current, {
      type: 'line',
      data: {
        labels: points.map((point) => formatTime(point.t)),
        datasets: [
          {
            label: 'Sentimento (janelas de 30s)',
            data: points.map((point) => point.score),
            borderColor: '#a855f7',
            segment: {
              borderColor: (ctx) => ((ctx.p1.parsed.y ?? 0) >= 0 ? '#34d399' : '#f87171'),
            },
            backgroundColor: 'rgba(168, 85, 247, 0.12)',
            fill: 'origin',
            pointRadius: points.map((point) => Math.min(2 + point.messages / 5, 6)),
            pointBackgroundColor: points.map((point) =>
              point.score >= 0 ? '#34d399' : '#f87171',
            ),
            tension: 0.3,
          },
          {
            label: 'Eventos',
            data: points.map((_, index) => (eventsByIndex.has(index) ? 0 : null)) as number[],
            showLine: false,
            pointStyle: 'triangle',
            pointRadius: 8,
            borderColor: '#facc15',
            backgroundColor: '#facc15',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (item) => {
                const point = points[item.dataIndex]
                return `${point.score >= 0 ? '+' : ''}${point.score} · ${point.messages} msgs`
              },
              afterBody: (items) => eventsByIndex.get(items[0]?.dataIndex ?? -1) ?? [],
            },
          },
        },
        scales: {
          x: { ticks: { color: '#71717a', maxTicksLimit: 10 }, grid: { color: '#27272a' } },
          y: {
            min: -1,
            max: 1,
            ticks: { color: '#71717a', stepSize: 0.5 },
            grid: { color: '#27272a' },
          },
        },
      },
    })
    return () => chartRef.current?.destroy()
  }, [community, events])

  if (community.sentiment_timeline.length === 0) return null
  return (
    <div className="h-40 w-full">
      <canvas ref={canvasRef} />
    </div>
  )
}

function SentimentBlock({
  community,
  events,
}: {
  community: CommunityOut
  events: EventMarker[]
}) {
  if (community.sentiment_overall === null) return null
  const overall = sentimentLabel(community.sentiment_overall)
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Sentimento do chat
        <span className="ml-2 normal-case tracking-normal">
          média{' '}
          <b className={overall.color}>
            {community.sentiment_overall > 0 ? '+' : ''}
            {community.sentiment_overall} ({overall.text})
          </b>
          <span className="ml-2 text-zinc-600">▲ = evento</span>
        </span>
      </p>
      <SentimentGauge score={community.sentiment_overall} />
      <div className="mt-3">
        <SentimentChart community={community} events={events} />
      </div>
      {community.sentiment_by_chatter.length > 0 && (
        <p className="mt-2 text-xs text-zinc-500">
          Por chatter:{' '}
          {community.sentiment_by_chatter.map((chatter) => {
            const label = sentimentLabel(chatter.score)
            return (
              <span key={chatter.login} className="mr-3">
                <span className="text-purple-400">{chatter.login}</span>{' '}
                <b className={label.color}>
                  {chatter.score > 0 ? '+' : ''}
                  {chatter.score}
                </b>
              </span>
            )
          })}
        </p>
      )}
    </div>
  )
}

function WordCloud({ community }: { community: CommunityOut }) {
  if (community.words.length === 0) return null
  const max = community.words[0].count
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Palavras mais usadas
      </p>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {community.words.map((word, index) => (
          <span
            key={word.word}
            title={`${word.count} vezes`}
            className={index % 3 === 0 ? 'text-purple-300' : index % 3 === 1 ? 'text-zinc-300' : 'text-sky-300'}
            style={{ fontSize: `${12 + 20 * Math.sqrt(word.count / max)}px` }}
          >
            {word.word}
          </span>
        ))}
      </div>
    </div>
  )
}

function EmoteChip({ emote }: { emote: CommunityOut['emotes'][number] }) {
  const [failed, setFailed] = useState(false)
  return (
    <span
      title={`${emote.name} · ${emote.count}x`}
      className="flex items-center gap-1.5 rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-xs"
    >
      {failed ? (
        <span>{emote.name}</span>
      ) : (
        <img
          src={`https://static-cdn.jtvnw.net/emoticons/v2/${emote.emote_id}/default/dark/1.0`}
          alt={emote.name}
          className="h-5 w-5"
          onError={() => setFailed(true)}
        />
      )}
      <span className="text-zinc-500">×{emote.count}</span>
    </span>
  )
}

function EmoteChips({ community }: { community: CommunityOut }) {
  if (community.emotes.length === 0) return null
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Emotes mais usados
      </p>
      <div className="flex flex-wrap gap-2">
        {community.emotes.map((emote) => (
          <EmoteChip key={`${emote.emote_id}-${emote.name}`} emote={emote} />
        ))}
      </div>
    </div>
  )
}

function PresenceHeatmap({ community }: { community: CommunityOut }) {
  if (community.presence.rows.length === 0) return null
  const max = Math.max(...community.presence.rows.flatMap((row) => row.cells), 1)
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Presença ao longo da live (top {community.presence.rows.length})
      </p>
      <div className="space-y-1 overflow-x-auto">
        {community.presence.rows.map((row) => (
          <div key={row.login} className="flex items-center gap-2">
            <span className="w-28 shrink-0 truncate text-xs text-purple-300">{row.login}</span>
            <div className="flex flex-1 gap-px">
              {row.cells.map((count, index) => (
                <div
                  key={index}
                  title={`${formatTime(community.presence.slots[index])}: ${count} msgs`}
                  className="h-4 flex-1 rounded-sm"
                  style={{
                    backgroundColor:
                      count === 0 ? '#27272a' : `rgba(168, 85, 247, ${0.25 + 0.75 * (count / max)})`,
                  }}
                />
              ))}
            </div>
          </div>
        ))}
        <div className="flex items-center gap-2 text-[10px] text-zinc-600">
          <span className="w-28 shrink-0" />
          <span>{formatTime(community.presence.slots[0])}</span>
          <span className="flex-1 text-right">
            {formatTime(community.presence.slots[community.presence.slots.length - 1])}
          </span>
        </div>
      </div>
    </div>
  )
}

export default function CommunitySection({
  streamId,
  events,
}: {
  streamId: number
  events: EventMarker[]
}) {
  const [community, setCommunity] = useState<CommunityOut | null>(null)

  useEffect(() => {
    apiGet<CommunityOut>(`/api/streams/${streamId}/community`)
      .then(setCommunity)
      .catch(() => setCommunity(null))
  }, [streamId])

  if (community === null || community.share.length === 0) return null

  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Comunidade</h3>
      <div className="space-y-5 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        <SentimentBlock community={community} events={events} />
        <EmoteChips community={community} />
        <WordCloud community={community} />
        <PresenceHeatmap community={community} />
      </div>
    </div>
  )
}
