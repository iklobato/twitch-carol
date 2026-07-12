import { useEffect, useState } from 'react'
import { apiGet, formatTime } from '../api'
import type { ChatterOut } from '../types'

function LabelChip({ label }: { label: string }) {
  const color = label.includes('seguiu')
    ? 'border-emerald-800 text-emerald-400'
    : label.includes('pico')
      ? 'border-orange-800 text-orange-400'
      : 'border-zinc-700 text-zinc-400'
  return <span className={`rounded-full border px-2 py-0.5 text-[10px] ${color}`}>{label}</span>
}

function ChatterRow({ chatter, maxMessages }: { chatter: ChatterOut; maxMessages: number }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mb-2 rounded-lg border border-zinc-800 bg-zinc-900 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => setOpen(!open)}
          className="min-w-32 text-left text-sm font-semibold text-purple-300 hover:text-purple-200"
        >
          {chatter.author_login}
        </button>
        <div className="hidden w-40 md:block">
          <div className="h-2 overflow-hidden rounded bg-zinc-800">
            <div
              className="h-full rounded bg-purple-500"
              style={{ width: `${(chatter.messages / maxMessages) * 100}%` }}
            />
          </div>
        </div>
        <span className="text-xs tabular-nums text-zinc-400">
          {chatter.messages.toLocaleString('pt-BR')} msgs · {chatter.pct_of_total}% do chat ·{' '}
          {chatter.active_minutes} min ativo
          {chatter.peak_messages > 0 && ` · ${chatter.peak_messages} em picos`}
        </span>
        <span className="flex flex-wrap gap-1">
          {chatter.labels.map((label) => (
            <LabelChip key={label} label={label} />
          ))}
        </span>
      </div>
      {open && (
        <div className="mt-2 space-y-1 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-sm">
          <p className="text-xs text-zinc-500">
            primeira mensagem {formatTime(chatter.first_at)} · última {formatTime(chatter.last_at)}
          </p>
          {chatter.sample_messages.map((message, index) => (
            <p key={index}>
              <span className="tabular-nums text-zinc-500">{formatTime(message.sent_at)}</span>{' '}
              {message.text}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

export default function ChattersSection({ streamId }: { streamId: number }) {
  const [chatters, setChatters] = useState<ChatterOut[] | null>(null)

  useEffect(() => {
    apiGet<ChatterOut[]>(`/api/streams/${streamId}/chatters`).then(setChatters)
  }, [streamId])

  if (chatters === null || chatters.length === 0) return null
  const maxMessages = chatters[0].messages

  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Quem participou</h3>
      {chatters.map((chatter) => (
        <ChatterRow key={chatter.author_login} chatter={chatter} maxMessages={maxMessages} />
      ))}
    </div>
  )
}
