import { useEffect, useState } from 'react'
import { apiGet, apiPost, formatDate, formatTime, STATUS_LABELS } from '../api'
import PipelineStepper from '../components/PipelineStepper'
import TimelineChart from '../components/TimelineChart'
import type {
  InsightOut,
  PeakDetail,
  PeakOut,
  QueueItem,
  StreamReport as Report,
  Timeline,
} from '../types'

const PROCESSING_POLL_MS = 10000
const TERMINAL_STATUSES = new Set(['ready', 'failed'])

const NUMBER_LABELS: Record<string, string> = {
  duration_minutes: 'Duração (min)',
  messages: 'Mensagens',
  chatters: 'Chatters únicos',
  peak_viewers: 'Pico de viewers',
  avg_viewers: 'Média de viewers',
  events: 'Eventos',
}

function NumbersRow({ report }: { report: Report }) {
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-6">
      {Object.entries(report.numbers).map(([key, comparison]) => (
        <div key={key} className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">{NUMBER_LABELS[key] ?? key}</p>
          <p className="text-lg font-bold">{comparison.value.toLocaleString('pt-BR')}</p>
          {comparison.delta_pct != null ? (
            <p className={`text-xs ${comparison.delta_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {comparison.delta_pct >= 0 ? '▲' : '▼'} {Math.abs(comparison.delta_pct)}% vs últimas 10
            </p>
          ) : (
            <p className="text-xs text-zinc-600">sem histórico</p>
          )}
        </div>
      ))}
    </div>
  )
}

function FeedbackButtons({ insight, onFeedback }: { insight: InsightOut; onFeedback: (value: string | null) => void }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <button
        onClick={() => onFeedback(insight.feedback === 'useful' ? null : 'useful')}
        className={`rounded border px-2 py-0.5 ${insight.feedback === 'useful' ? 'border-emerald-600 text-emerald-400' : 'border-zinc-700 text-zinc-500 hover:text-zinc-300'}`}
      >
        👍 Útil
      </button>
      <button
        onClick={() => onFeedback(insight.feedback === 'not_useful' ? null : 'not_useful')}
        className={`rounded border px-2 py-0.5 ${insight.feedback === 'not_useful' ? 'border-red-700 text-red-400' : 'border-zinc-700 text-zinc-500 hover:text-zinc-300'}`}
      >
        👎 Inútil
      </button>
    </div>
  )
}

function SummaryHero({ insight, onFeedback }: { insight: InsightOut; onFeedback: (value: string | null) => void }) {
  const [open, setOpen] = useState(false)
  return (
    <section className="mb-6 rounded-xl border border-purple-900/70 bg-gradient-to-b from-purple-950/40 to-zinc-900 p-6">
      <p className="mb-2 text-xs font-bold uppercase tracking-widest text-purple-400">Resumo da live</p>
      <p className="mb-4 max-w-3xl text-base leading-relaxed">{insight.content}</p>
      {insight.cited_segments.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {insight.cited_segments.map((segment) => (
            <button
              key={segment.id}
              onClick={() => setOpen(!open)}
              className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-400 hover:border-purple-500 hover:text-zinc-200"
            >
              🎙 <span className="font-semibold text-purple-400">{formatTime(segment.started_at)}</span>{' '}
              "{(segment.text ?? '').slice(0, 42)}{(segment.text ?? '').length > 42 ? '…' : ''}"
            </button>
          ))}
        </div>
      )}
      {open && (
        <div className="mb-3 space-y-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-sm">
          {insight.cited_segments.map((segment) => (
            <p key={segment.id}>
              <span className="tabular-nums text-zinc-500">{formatTime(segment.started_at)}</span>{' '}
              {segment.text}
            </p>
          ))}
        </div>
      )}
      <FeedbackButtons insight={insight} onFeedback={onFeedback} />
    </section>
  )
}

function Sparkline({ timeline, peak }: { timeline: Timeline; peak: PeakOut }) {
  const start = new Date(peak.window_start).getTime() - 3 * 60000
  const end = new Date(peak.window_end).getTime() + 3 * 60000
  const points = timeline.chat.filter((point) => {
    const t = new Date(point.t).getTime()
    return t >= start && t <= end
  })
  if (points.length === 0) return null
  const max = Math.max(...points.map((point) => point.value))
  return (
    <div className="mt-2 flex h-7 items-end gap-0.5">
      {points.map((point) => {
        const t = new Date(point.t).getTime()
        const hot =
          t >= new Date(peak.window_start).getTime() && t < new Date(peak.window_end).getTime()
        return (
          <span
            key={point.t}
            className={`w-2 rounded-sm ${hot ? 'bg-orange-500' : 'bg-zinc-700'}`}
            style={{ height: `${Math.max(8, (point.value / max) * 100)}%` }}
          />
        )
      })}
    </div>
  )
}

function MomentCard({
  report,
  timeline,
  peak,
  insight,
  onFeedback,
}: {
  report: Report
  timeline: Timeline | null
  peak: PeakOut
  insight: InsightOut | undefined
  onFeedback: (insight: InsightOut, value: string | null) => void
}) {
  const [showCited, setShowCited] = useState(false)
  const [fullChat, setFullChat] = useState(false)
  const [detail, setDetail] = useState<PeakDetail | null>(null)

  useEffect(() => {
    if (fullChat && detail === null) {
      apiGet<PeakDetail>(`/api/streams/${report.id}/peaks/${peak.id}`).then(setDetail)
    }
  }, [fullChat, detail, report.id, peak.id])

  const citedIds = new Set(insight?.cited_messages.map((message) => message.id))

  return (
    <div className="mb-3 rounded-xl border border-zinc-800 border-l-4 border-l-orange-500 bg-zinc-900 p-4">
      <div className="flex flex-wrap gap-x-6 gap-y-2 md:flex-nowrap">
        <div className="w-24 shrink-0">
          <p className="text-lg font-bold tabular-nums text-orange-400">{formatTime(peak.window_start)}</p>
          <p className="text-xs text-zinc-500">{peak.score.toFixed(1)}x o ritmo</p>
          {timeline && <Sparkline timeline={timeline} peak={peak} />}
        </div>
        <div className="min-w-0 flex-1">
          {insight ? (
            <p className="mb-3 text-sm leading-relaxed">{insight.content}</p>
          ) : (
            <p className="mb-3 text-sm text-zinc-500">
              Pico detectado; sem explicação publicada (evidência não verificável ou orçamento).
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {insight && insight.cited_messages.length > 0 && (
              <button
                onClick={() => setShowCited(!showCited)}
                className="rounded-full border border-zinc-700 px-3 py-1 text-xs text-zinc-400 hover:border-orange-500 hover:text-zinc-200"
              >
                💬 {insight.cited_messages.length} mensagens citadas
              </button>
            )}
            <button
              onClick={() => setFullChat(!fullChat)}
              className="rounded-full border border-zinc-700 px-3 py-1 text-xs text-zinc-400 hover:border-orange-500 hover:text-zinc-200"
            >
              abrir transcrição + chat
            </button>
            {insight && <FeedbackButtons insight={insight} onFeedback={(value) => onFeedback(insight, value)} />}
          </div>
        </div>
      </div>

      {showCited && insight && (
        <div className="mt-3 max-h-48 space-y-1 overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-sm">
          {insight.cited_messages.map((message) => (
            <p key={message.id}>
              <span className="tabular-nums text-zinc-500">{formatTime(message.sent_at)}</span>{' '}
              <span className="text-purple-400">{message.author_login}:</span> {message.text}
            </p>
          ))}
        </div>
      )}

      {fullChat && detail && (
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">O que você estava falando</p>
            <div className="max-h-64 space-y-2 overflow-y-auto pr-2 text-sm">
              {detail.segments.length === 0 && <p className="text-zinc-500">Sem transcrição nesta janela.</p>}
              {detail.segments.map((segment) => (
                <p key={segment.id}>
                  <span className="tabular-nums text-zinc-500">{formatTime(segment.started_at)}</span>{' '}
                  {segment.kind === 'speech' ? segment.text : <em className="text-zinc-500">[{segment.kind}]</em>}
                </p>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">O que o chat dizia</p>
            <div className="max-h-64 space-y-1 overflow-y-auto pr-2 text-sm">
              {detail.messages.map((message) => (
                <p key={message.id} className={citedIds.has(message.id) ? 'rounded bg-purple-950/50 px-1' : ''}>
                  <span className="tabular-nums text-zinc-500">{formatTime(message.sent_at)}</span>{' '}
                  <span className="text-purple-400">{message.author_login}:</span> {message.text}
                </p>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function TopicRow({ insight, onFeedback }: { insight: InsightOut; onFeedback: (value: string | null) => void }) {
  const [name, ...rest] = insight.content.split('\n')
  const description = rest.join(' ').trim()
  const rank = typeof insight.evidence.rank === 'number' ? insight.evidence.rank : null
  const [open, setOpen] = useState(false)
  return (
    <div className="mb-2 rounded-lg border border-zinc-800 bg-zinc-900 p-3">
      <div className="flex items-center gap-3">
        <span className="w-7 shrink-0 text-sm font-bold tabular-nums text-zinc-500">
          {rank != null ? `${rank}º` : '·'}
        </span>
        <div className="min-w-0 flex-1">
          <button onClick={() => setOpen(!open)} className="text-left text-sm font-semibold hover:text-purple-300">
            {name}
          </button>
          {description && <p className="text-xs text-zinc-500">{description}</p>}
        </div>
        {insight.engagement_pct != null && (
          <div className="hidden w-44 shrink-0 md:block">
            <div className="h-2 overflow-hidden rounded bg-zinc-800">
              <div className="h-full rounded bg-purple-500" style={{ width: `${insight.engagement_pct}%` }} />
            </div>
            <p className="mt-0.5 text-right text-[10px] text-zinc-600">engajamento do chat</p>
          </div>
        )}
        <FeedbackButtons insight={insight} onFeedback={onFeedback} />
      </div>
      {open && insight.cited_segments.length > 0 && (
        <div className="ml-10 mt-2 space-y-1 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-sm">
          {insight.cited_segments.map((segment) => (
            <p key={segment.id}>
              <span className="tabular-nums text-zinc-500">{formatTime(segment.started_at)}</span>{' '}
              {segment.text}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function AuditNotes({ audit }: { audit: Record<string, unknown> | null }) {
  if (!audit) return null
  const chat = audit.chat as { disconnects?: number; gap_seconds?: number } | undefined
  const viewers = audit.viewers as { samples?: number; expected?: number } | undefined
  const notes: string[] = []
  if (chat?.disconnects) {
    notes.push(`chat teve ${chat.disconnects} desconexão(ões), ~${Math.round(chat.gap_seconds ?? 0)}s perdidos`)
  }
  if (viewers?.samples != null && viewers?.expected != null && viewers.samples < viewers.expected) {
    notes.push(`amostras de viewers incompletas (${viewers.samples}/${viewers.expected})`)
  }
  if (notes.length === 0) return null
  return (
    <div className="mb-4 rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-sm text-amber-200/90">
      Lacunas de captura: {notes.join('; ')}.
    </div>
  )
}

export default function StreamReport({ streamId }: { streamId: number }) {
  const [report, setReport] = useState<Report | null>(null)
  const [timeline, setTimeline] = useState<Timeline | null>(null)
  const [queue, setQueue] = useState<QueueItem | null>(null)
  const processing = report !== null && !TERMINAL_STATUSES.has(report.status)

  useEffect(() => {
    function load() {
      apiGet<Report>(`/api/streams/${streamId}`).then(setReport)
      apiGet<Timeline>(`/api/streams/${streamId}/timeline`).then(setTimeline)
      apiGet<QueueItem[]>('/api/queue').then((items) =>
        setQueue(items.find((item) => item.stream_id === streamId) ?? null),
      )
    }
    load()
    if (!processing) return
    const timer = setInterval(load, PROCESSING_POLL_MS)
    return () => clearInterval(timer)
  }, [streamId, processing])

  async function sendFeedback(insight: InsightOut, value: string | null) {
    await apiPost(`/api/insights/${insight.id}/feedback`, { feedback: value })
    setReport((current) =>
      current && {
        ...current,
        insights: current.insights.map((item) =>
          item.id === insight.id ? { ...item, feedback: value } : item,
        ),
      },
    )
  }

  if (report === null) return <p className="text-zinc-400">Carregando relatório...</p>

  const summary = report.insights.find((insight) => insight.type === 'summary')
  const peakInsights = new Map(
    report.insights
      .filter((insight) => insight.type === 'peak_explanation')
      .map((insight) => [insight.evidence.peak_id as number, insight]),
  )
  const topics = report.insights
    .filter((insight) => insight.type === 'topic')
    .sort((a, b) => ((a.evidence.rank as number) ?? 99) - ((b.evidence.rank as number) ?? 99))
  const momentPeaks = [...report.peaks].sort(
    (a, b) => new Date(a.window_start).getTime() - new Date(b.window_start).getTime(),
  )

  return (
    <div>
      <a href="#/" className="text-sm text-zinc-400 hover:text-zinc-200">← voltar</a>
      <h2 className="mb-1 mt-2 text-xl font-bold">{report.title ?? `Live #${report.id}`}</h2>
      <p className="mb-4 text-sm text-zinc-400">
        {formatDate(report.started_at)} {formatTime(report.started_at)}
        {report.ended_at && ` – ${formatTime(report.ended_at)}`} ·{' '}
        {STATUS_LABELS[report.status] ?? report.status}
      </p>

      <PipelineStepper status={report.status} queue={queue} />
      <AuditNotes audit={report.audit} />
      {summary && <SummaryHero insight={summary} onFeedback={(value) => sendFeedback(summary, value)} />}
      <NumbersRow report={report} />

      {timeline && (
        <div className="mb-6 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <TimelineChart timeline={timeline} />
        </div>
      )}

      {momentPeaks.length > 0 && (
        <div className="mb-6">
          <h3 className="mb-3 text-lg font-bold">Momentos da live</h3>
          {momentPeaks.map((peak) => (
            <MomentCard
              key={peak.id}
              report={report}
              timeline={timeline}
              peak={peak}
              insight={peakInsights.get(peak.id)}
              onFeedback={sendFeedback}
            />
          ))}
        </div>
      )}

      {topics.length > 0 && (
        <div className="mb-6">
          <h3 className="mb-3 text-lg font-bold">Assuntos da live</h3>
          {topics.map((topic) => (
            <TopicRow key={topic.id} insight={topic} onFeedback={(value) => sendFeedback(topic, value)} />
          ))}
        </div>
      )}

      {!summary && topics.length === 0 && peakInsights.size === 0 && (
        <p className="text-sm text-zinc-500">
          Nenhum insight publicado para esta live (sem evidência verificável ou análise pendente).
        </p>
      )}
    </div>
  )
}
