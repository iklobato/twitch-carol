import { ArcElement, Chart, DoughnutController, Legend, Tooltip } from 'chart.js'
import { useEffect, useRef, useState } from 'react'
import { apiGet, formatTime } from '../api'
import type { CommunityOut } from '../types'

Chart.register(DoughnutController, ArcElement, Tooltip, Legend)

const DONUT_COLORS = ['#a855f7', '#38bdf8', '#f97316', '#34d399', '#facc15', '#52525b']

function ShareDonut({ community }: { community: CommunityOut }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const chartRef = useRef<Chart | null>(null)

  useEffect(() => {
    if (!canvasRef.current) return
    chartRef.current?.destroy()
    chartRef.current = new Chart(canvasRef.current, {
      type: 'doughnut',
      data: {
        labels: community.share.map((slice) => slice.login ?? 'outros'),
        datasets: [
          {
            data: community.share.map((slice) => slice.messages),
            backgroundColor: DONUT_COLORS,
            borderColor: '#18181b',
          },
        ],
      },
      options: {
        plugins: { legend: { position: 'right', labels: { color: '#d4d4d8', boxWidth: 12 } } },
      },
    })
    return () => chartRef.current?.destroy()
  }, [community])

  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Fatia do chat
      </p>
      <canvas ref={canvasRef} className="max-h-44" />
    </div>
  )
}

function sentimentLabel(score: number): { text: string; color: string } {
  if (score > 0.15) return { text: 'positivo', color: 'text-emerald-400' }
  if (score < -0.15) return { text: 'negativo', color: 'text-red-400' }
  return { text: 'neutro', color: 'text-zinc-400' }
}

function SentimentBlock({ community }: { community: CommunityOut }) {
  if (community.sentiment_overall === null) return null
  const overall = sentimentLabel(community.sentiment_overall)
  const max = Math.max(...community.sentiment_timeline.map((point) => point.messages), 1)
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
        </span>
      </p>
      <div className="flex h-16 items-center gap-0.5">
        {community.sentiment_timeline.map((point) => {
          const positive = point.score >= 0
          const height = Math.max(6, Math.abs(point.score) * 56)
          return (
            <div
              key={point.t}
              title={`${formatTime(point.t)}: ${point.score} (${point.messages} msgs c/ sentimento)`}
              className="flex h-full flex-1 flex-col justify-center"
              style={{ opacity: 0.35 + 0.65 * (point.messages / max) }}
            >
              <div
                className={`w-full rounded-sm ${positive ? 'self-end bg-emerald-500' : 'bg-red-500'}`}
                style={{ height: `${height}%` }}
              />
            </div>
          )
        })}
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

function EmoteChips({ community }: { community: CommunityOut }) {
  if (community.emotes.length === 0) return null
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Emotes mais usados
      </p>
      <div className="flex flex-wrap gap-2">
        {community.emotes.map((emote) => (
          <span
            key={emote.name}
            className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs"
          >
            {emote.name} <span className="text-zinc-500">×{emote.count}</span>
          </span>
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

export default function CommunitySection({ streamId }: { streamId: number }) {
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
        <div className="grid gap-6 md:grid-cols-2">
          <ShareDonut community={community} />
          <div className="space-y-5">
            <SentimentBlock community={community} />
            <EmoteChips community={community} />
          </div>
        </div>
        <WordCloud community={community} />
        <PresenceHeatmap community={community} />
      </div>
    </div>
  )
}
