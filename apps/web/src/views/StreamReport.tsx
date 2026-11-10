import { useEffect, useState } from 'react'
import { apiGet, apiPost, formatDate, formatTime, statusLabel } from '../api'
import { fmtInt, t, type MessageKey } from '../i18n'
import ActionableSection from '../components/ActionableSection'
import ChattersSection from '../components/ChattersSection'
import FinanceSection from '../components/FinanceSection'
import CommunitySection from '../components/CommunitySection'
import PipelineStepper from '../components/PipelineStepper'
import TimelineChart from '../components/TimelineChart'
import type {
  ActionableOut,
  InsightOut,
  PeakDetail,
  PeakOut,
  QueueItem,
  StreamReport as Report,
  Timeline,
  TopicDetail,
} from '../types'

function scrollToPeak(peakId: number) {
  const el = document.getElementById(`momento-${peakId}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('ring-2', 'ring-accent')
    setTimeout(() => el.classList.remove('ring-2', 'ring-accent'), 1600)
  }
}

export type ReportTab = 'moments' | 'improve' | 'money' | 'topics' | 'chat'

/** Moments and topics only get a tab when the live has some; the other three
 * always have something to say (or an empty state of their own). */
export function availableTabs(peaks: number, topics: number): ReportTab[] {
  const tabs: ReportTab[] = []
  if (peaks > 0) tabs.push('moments')
  tabs.push('improve', 'money')
  if (topics > 0) tabs.push('topics')
  tabs.push('chat')
  return tabs
}

const TAB_LABEL: Record<ReportTab, MessageKey> = {
  moments: 'report.tab.moments',
  improve: 'report.tab.improve',
  money: 'report.tab.money',
  topics: 'report.tab.topics',
  chat: 'report.tab.chat',
}

const PROCESSING_POLL_MS = 10000
const TERMINAL_STATUSES = new Set(['ready', 'failed'])

function NumbersRow({ report }: { report: Report }) {
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-6">
      {Object.entries(report.numbers).map(([key, comparison]) => (
        <div key={key} className="rounded-2xl border border-line bg-panel p-3">
          <p className="text-xs text-ink-faint">{t(`numbers.${key}` as MessageKey)}</p>
          <p className="text-lg font-bold">{fmtInt(comparison.value)}</p>
          {comparison.delta_pct != null ? (
            <p
              className={`text-xs ${comparison.delta_pct >= 0 ? 'text-money' : 'text-alert'}`}
            >
              {comparison.delta_pct >= 0 ? '▲' : '▼'} {Math.abs(comparison.delta_pct)}%{' '}
              {t('report.vsLast10')}
            </p>
          ) : (
            <p className="text-xs text-ink-faint">{t('report.noHistory')}</p>
          )}
        </div>
      ))}
    </div>
  )
}

function FeedbackButtons({
  insight,
  onFeedback,
}: {
  insight: InsightOut
  onFeedback: (value: string | null) => void
}) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <button
        onClick={() => onFeedback(insight.feedback === 'useful' ? null : 'useful')}
        className={`rounded border px-2 py-0.5 ${insight.feedback === 'useful' ? 'border-emerald-600 text-money' : 'border-line-strong text-ink-faint hover:text-ink'}`}
      >
        {t('feedback.useful')}
      </button>
      <button
        onClick={() => onFeedback(insight.feedback === 'not_useful' ? null : 'not_useful')}
        className={`rounded border px-2 py-0.5 ${insight.feedback === 'not_useful' ? 'border-red-700 text-alert' : 'border-line-strong text-ink-faint hover:text-ink'}`}
      >
        {t('feedback.notUseful')}
      </button>
    </div>
  )
}

function SummaryHero({
  insight,
  onFeedback,
}: {
  insight: InsightOut
  onFeedback: (value: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <section className="mb-6 rounded-2xl border border-line bg-panel p-6">
      <p className="mb-2 text-xs font-bold uppercase tracking-widest text-accent-ink">
        {t('report.summary')}
      </p>
      <p className="mb-4 max-w-3xl text-base leading-relaxed">{insight.content}</p>
      {insight.cited_segments.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {insight.cited_segments.map((segment) => (
            <button
              key={segment.id}
              onClick={() => setOpen(!open)}
              className="rounded-full border border-line-strong bg-panel px-3 py-1 text-xs text-ink-muted hover:border-accent hover:text-ink"
            >
              🎙{' '}
              <span className="font-semibold text-accent-ink">
                {formatTime(segment.started_at)}
              </span>{' '}
              "{(segment.text ?? '').slice(0, 42)}
              {(segment.text ?? '').length > 42 ? '…' : ''}"
            </button>
          ))}
        </div>
      )}
      {open && (
        <div className="mb-3 space-y-2 rounded-lg border border-line bg-canvas p-3 text-sm">
          {insight.cited_segments.map((segment) => (
            <p key={segment.id}>
              <span className="tabular-nums text-ink-faint">{formatTime(segment.started_at)}</span>{' '}
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
    const time = new Date(point.t).getTime()
    return time >= start && time <= end
  })
  if (points.length === 0) return null
  const max = Math.max(...points.map((point) => point.value))
  return (
    <div className="mt-2 flex h-7 items-end gap-0.5">
      {points.map((point) => {
        const time = new Date(point.t).getTime()
        const hot =
          time >= new Date(peak.window_start).getTime() &&
          time < new Date(peak.window_end).getTime()
        return (
          <span
            key={point.t}
            className={`w-2 rounded-sm ${hot ? 'bg-accent' : 'bg-line-strong'}`}
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
    <div
      id={`momento-${peak.id}`}
      className="mb-3 rounded-2xl border border-line bg-panel p-4 transition-all"
    >
      <div className="flex flex-wrap gap-x-6 gap-y-2 md:flex-nowrap">
        <div className="w-24 shrink-0">
          <p className="text-lg font-bold tabular-nums text-accent-ink">
            {formatTime(peak.window_start)}
          </p>
          <p className="text-xs text-ink-faint">
            {t('moment.rate', { score: peak.score.toFixed(1) })}
          </p>
          {timeline && <Sparkline timeline={timeline} peak={peak} />}
        </div>
        <div className="min-w-0 flex-1">
          {insight ? (
            <p className="mb-3 text-sm leading-relaxed">{insight.content}</p>
          ) : (
            <p className="mb-3 text-sm text-ink-faint">{t('moment.noExplanation')}</p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {insight && insight.cited_messages.length > 0 && (
              <button
                onClick={() => setShowCited(!showCited)}
                className="rounded-full border border-line-strong px-3 py-1 text-xs text-ink-muted hover:border-accent hover:text-ink"
              >
                {t('moment.citedMessages', { n: insight.cited_messages.length })}
              </button>
            )}
            <button
              onClick={() => setFullChat(!fullChat)}
              className="rounded-full border border-line-strong px-3 py-1 text-xs text-ink-muted hover:border-accent hover:text-ink"
            >
              {t('moment.openTranscript')}
            </button>
            {insight && (
              <FeedbackButtons
                insight={insight}
                onFeedback={(value) => onFeedback(insight, value)}
              />
            )}
          </div>
        </div>
      </div>

      {showCited && insight && (
        <div className="mt-3 max-h-48 space-y-1 overflow-y-auto rounded-lg border border-line bg-canvas p-3 text-sm">
          {insight.cited_messages.map((message) => (
            <p key={message.id}>
              <span className="tabular-nums text-ink-faint">{formatTime(message.sent_at)}</span>{' '}
              <span className="text-accent-ink">{message.author_login}:</span> {message.text}
            </p>
          ))}
        </div>
      )}

      {fullChat && detail && (
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              {t('moment.youWereSaying')}
            </p>
            <div className="max-h-64 space-y-2 overflow-y-auto pr-2 text-sm">
              {detail.segments.length === 0 && (
                <p className="text-ink-faint">{t('moment.noTranscript')}</p>
              )}
              {detail.segments.map((segment) => (
                <p key={segment.id}>
                  <span className="tabular-nums text-ink-faint">
                    {formatTime(segment.started_at)}
                  </span>{' '}
                  {segment.kind === 'speech' ? (
                    segment.text
                  ) : (
                    <em className="text-ink-faint">[{segment.kind}]</em>
                  )}
                </p>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              {t('moment.chatWasSaying')}
            </p>
            <div className="max-h-64 space-y-1 overflow-y-auto pr-2 text-sm">
              {detail.messages.map((message) => (
                <p
                  key={message.id}
                  className={citedIds.has(message.id) ? 'rounded bg-accent-soft px-1' : ''}
                >
                  <span className="tabular-nums text-ink-faint">{formatTime(message.sent_at)}</span>{' '}
                  <span className="text-accent-ink">{message.author_login}:</span> {message.text}
                </p>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function TopicDetailPanel({ streamId, insightId }: { streamId: number; insightId: number }) {
  const [detail, setDetail] = useState<TopicDetail | null>(null)

  useEffect(() => {
    apiGet<TopicDetail>(`/api/streams/${streamId}/topics/${insightId}`)
      .then(setDetail)
      .catch(() => setDetail(null))
  }, [streamId, insightId])

  if (detail === null)
    return <p className="ml-10 mt-2 text-xs text-ink-faint">{t('topic.loadingDetails')}</p>

  return (
    <div className="ml-10 mt-2 space-y-3 rounded-lg border border-line bg-canvas p-3 text-sm">
      <p className="text-xs text-ink-muted">
        {t('topic.window', {
          start: formatTime(detail.window_start),
          end: formatTime(detail.window_end),
          n: fmtInt(detail.messages_in_window),
        })}
        {detail.chat_rate_lift != null && t('topic.lift', { n: detail.chat_rate_lift })}
      </p>
      {detail.top_chatters.length > 0 && (
        <p className="text-xs text-ink-muted">
          {t('topic.topChatters')}{' '}
          {detail.top_chatters.map((chatter) => (
            <span key={chatter.author_login} className="mr-2 text-accent-ink">
              {chatter.author_login} ({chatter.messages})
            </span>
          ))}
        </p>
      )}
      {detail.top_words.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">
            {t('topic.words')}
          </p>
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            {detail.top_words.map((word) => (
              <span
                key={word.word}
                title={t('words.times', { n: word.count })}
                className="text-sky-300"
                style={{ fontSize: `${12 + Math.min(word.count, 10)}px` }}
              >
                {word.word}
              </span>
            ))}
          </div>
        </div>
      )}
      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">
          {t('topic.youSaid')}
        </p>
        {detail.cited_segments.map((segment) => (
          <p key={segment.id}>
            <span className="tabular-nums text-ink-faint">{formatTime(segment.started_at)}</span>{' '}
            {segment.text}
          </p>
        ))}
      </div>
      {detail.sample_messages.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">
            {t('topic.chatThen')}
          </p>
          {detail.sample_messages.map((message) => (
            <p key={message.id}>
              <span className="tabular-nums text-ink-faint">{formatTime(message.sent_at)}</span>{' '}
              <span className="text-accent-ink">{message.author_login}:</span> {message.text}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function TopicRow({
  streamId,
  insight,
  onFeedback,
}: {
  streamId: number
  insight: InsightOut
  onFeedback: (value: string | null) => void
}) {
  const [name, ...rest] = insight.content.split('\n')
  const description = rest.join(' ').trim()
  const rank = typeof insight.evidence.rank === 'number' ? insight.evidence.rank : null
  const [open, setOpen] = useState(false)
  return (
    <div className="mb-2 rounded-2xl border border-line bg-panel p-3">
      <div className="flex items-center gap-3">
        <span className="w-7 shrink-0 text-sm font-bold tabular-nums text-ink-faint">
          {rank != null ? `${rank}.` : '·'}
        </span>
        <div className="min-w-0 flex-1">
          <button
            onClick={() => setOpen(!open)}
            className="text-left text-sm font-semibold hover:text-ink"
          >
            {name}{' '}
            <span className="text-xs font-normal text-ink-faint">
              {open ? '▲' : t('topic.details')}
            </span>
          </button>
          {description && <p className="text-xs text-ink-faint">{description}</p>}
        </div>
        {insight.engagement_pct != null && (
          <div className="hidden w-44 shrink-0 md:block">
            <div className="h-2 overflow-hidden rounded bg-line">
              <div
                className="h-full rounded bg-accent"
                style={{ width: `${insight.engagement_pct}%` }}
              />
            </div>
            <p className="mt-0.5 text-right text-[10px] text-ink-faint">{t('topic.engagement')}</p>
          </div>
        )}
        <FeedbackButtons insight={insight} onFeedback={onFeedback} />
      </div>
      {open && <TopicDetailPanel streamId={streamId} insightId={insight.id} />}
    </div>
  )
}

function AuditNotes({ audit }: { audit: Record<string, unknown> | null }) {
  if (!audit) return null
  const chat = audit.chat as { disconnects?: number; gap_seconds?: number } | undefined
  const viewers = audit.viewers as { samples?: number; expected?: number } | undefined
  const notes: string[] = []
  if (chat?.disconnects) {
    notes.push(
      t('audit.chatDisconnects', {
        n: chat.disconnects,
        seconds: Math.round(chat.gap_seconds ?? 0),
      }),
    )
  }
  if (viewers?.samples != null && viewers?.expected != null && viewers.samples < viewers.expected) {
    notes.push(t('audit.viewerSamples', { got: viewers.samples, expected: viewers.expected }))
  }
  if (notes.length === 0) return null
  return (
    <div className="mb-4 rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-sm text-amber-200/90">
      {t('audit.gaps', { notes: notes.join('; ') })}
    </div>
  )
}

function TldrCard({
  report,
  actionable,
  topics,
  topPeak,
  onPeak,
}: {
  report: Report
  actionable: ActionableOut | null
  topics: InsightOut[]
  topPeak: PeakOut | null
  onPeak: (peakId: number) => void
}) {
  const bullets: { text: React.ReactNode }[] = []
  if (topPeak) {
    bullets.push({
      text: (
        <>
          {t('tldr.bestMoment')}{' '}
          <button
            onClick={() => onPeak(topPeak.id)}
            className="font-semibold text-accent-ink underline hover:text-ink"
          >
            {t('tldr.peakScore', {
              time: formatTime(topPeak.window_start),
              score: topPeak.score.toFixed(1),
            })}
          </button>
        </>
      ),
    })
  }
  if (topics[0]) {
    bullets.push({
      text: (
        <>
          {t('tldr.topTopic')}{' '}
          <span className="font-semibold">{topics[0].content.split('\n')[0]}</span>
        </>
      ),
    })
  }
  if (actionable?.retention) {
    bullets.push({
      text: (
        <>
          {t('tldr.retention')}{' '}
          <span className="font-semibold">{actionable.retention.retained_pct}%</span>{' '}
          {t('tldr.retentionSuffix')}
        </>
      ),
    })
  }
  const messages = report.numbers.messages
  if (messages) {
    bullets.push({
      text: (
        <>
          <span className="font-semibold">{fmtInt(messages.value)}</span> {t('tldr.messages')}
          {messages.delta_pct != null &&
            t('tldr.messagesDelta', {
              sign: messages.delta_pct >= 0 ? '+' : '',
              pct: messages.delta_pct,
            })}
        </>
      ),
    })
  }
  if (bullets.length === 0) return null

  return (
    <section className="rounded-2xl border border-accent/30 bg-accent-soft p-5">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink-faint">
        {t('tldr.title')}
      </p>
      <ul className="grid gap-x-6 gap-y-2 text-sm md:grid-cols-2">
        {bullets.map((bullet, index) => (
          <li key={index}>{bullet.text}</li>
        ))}
      </ul>
    </section>
  )
}

export default function StreamReport({ streamId }: { streamId: number }) {
  const [report, setReport] = useState<Report | null>(null)
  const [timeline, setTimeline] = useState<Timeline | null>(null)
  const [queue, setQueue] = useState<QueueItem | null>(null)
  const [actionable, setActionable] = useState<ActionableOut | null>(null)
  const [chosenTab, setChosenTab] = useState<ReportTab | null>(null)
  const [pendingPeak, setPendingPeak] = useState<number | null>(null)
  const processing = report !== null && !TERMINAL_STATUSES.has(report.status)

  useEffect(() => {
    function load() {
      apiGet<Report>(`/api/streams/${streamId}`).then(setReport)
      apiGet<Timeline>(`/api/streams/${streamId}/timeline`).then(setTimeline)
      apiGet<QueueItem[]>('/api/queue').then((items) =>
        setQueue(items.find((item) => item.stream_id === streamId) ?? null),
      )
      apiGet<ActionableOut>(`/api/streams/${streamId}/actionable`)
        .then(setActionable)
        .catch(() => setActionable(null))
    }
    load()
    if (!processing) return
    const timer = setInterval(load, PROCESSING_POLL_MS)
    return () => clearInterval(timer)
  }, [streamId, processing])

  // A peak lives in the Moments tab: open it first, scroll once it is rendered.
  useEffect(() => {
    if (pendingPeak === null) return
    scrollToPeak(pendingPeak)
    setPendingPeak(null)
  }, [pendingPeak])

  function goToPeak(peakId: number) {
    setChosenTab('moments')
    setPendingPeak(peakId)
  }

  async function sendFeedback(insight: InsightOut, value: string | null) {
    await apiPost(`/api/insights/${insight.id}/feedback`, { feedback: value })
    setReport((current) =>
      current
        ? {
            ...current,
            insights: current.insights.map((item) =>
              item.id === insight.id ? { ...item, feedback: value } : item,
            ),
          }
        : current,
    )
  }

  if (report === null) return <p className="text-ink-muted">{t('report.loading')}</p>

  const summary = report.insights.find((insight) => insight.type === 'summary')
  const peakInsights = new Map(
    report.insights
      .filter((insight) => insight.type === 'peak_explanation')
      .map((insight) => [insight.evidence.peak_id as number, insight]),
  )
  const topics = report.insights
    .filter((insight) => insight.type === 'topic')
    .sort((a, b) => ((a.evidence.rank as number) ?? 99) - ((b.evidence.rank as number) ?? 99))
  const recommendations = report.insights
    .filter((insight) => insight.type === 'recommendation')
    .sort((a, b) => ((a.evidence.rank as number) ?? 99) - ((b.evidence.rank as number) ?? 99))
  const momentPeaks = [...report.peaks].sort(
    (a, b) => new Date(a.window_start).getTime() - new Date(b.window_start).getTime(),
  )
  const topPeak = report.peaks.reduce<PeakOut | null>(
    (best, peak) => (best === null || peak.score > best.score ? peak : best),
    null,
  )

  const tabs = availableTabs(momentPeaks.length, topics.length)
  const tab = chosenTab !== null && tabs.includes(chosenTab) ? chosenTab : tabs[0]
  const tabCount: Partial<Record<ReportTab, number>> = {
    moments: momentPeaks.length,
    topics: topics.length,
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <a href="#/" className="inline-flex min-h-11 items-center text-sm text-ink-muted hover:text-ink">
          {t('nav.back')}
        </a>
        <h1 className="font-display text-3xl font-semibold">
          {report.title ?? t('live.number', { id: report.id })}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">
          {formatDate(report.started_at)} {formatTime(report.started_at)}
          {report.ended_at && ` – ${formatTime(report.ended_at)}`} · {statusLabel(report.status)}
        </p>
      </div>

      <PipelineStepper status={report.status} queue={queue} />
      <AuditNotes audit={report.audit} />
      {report.status === 'ready' && (
        <TldrCard
          report={report}
          actionable={actionable}
          topics={topics}
          topPeak={topPeak}
          onPeak={goToPeak}
        />
      )}
      {summary && (
        <SummaryHero insight={summary} onFeedback={(value) => sendFeedback(summary, value)} />
      )}
      <NumbersRow report={report} />

      {timeline && (
        <div className="rounded-2xl border border-line bg-panel p-4">
          <TimelineChart timeline={timeline} onPeakClick={goToPeak} />
        </div>
      )}

      <div role="tablist" aria-label={t('report.tabs')} className="flex gap-1 overflow-x-auto border-b border-line">
        {tabs.map((id) => (
          <button
            key={id}
            id={`tab-${id}`}
            role="tab"
            aria-selected={id === tab}
            aria-controls={`panel-${id}`}
            onClick={() => setChosenTab(id)}
            className={`min-h-11 shrink-0 border-b-2 px-4 text-sm font-semibold ${
              id === tab ? 'border-accent text-ink' : 'border-transparent text-ink-muted hover:text-ink'
            }`}
          >
            {t(TAB_LABEL[id])}
            {tabCount[id] !== undefined && ` (${tabCount[id]})`}
          </button>
        ))}
      </div>

      <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === 'moments' &&
          momentPeaks.map((peak) => (
            <MomentCard
              key={peak.id}
              report={report}
              timeline={timeline}
              peak={peak}
              insight={peakInsights.get(peak.id)}
              onFeedback={sendFeedback}
            />
          ))}

        {tab === 'improve' && (
          <>
            <ActionableSection actionable={actionable} />
            {recommendations.length > 0 && (
              <div className="mb-6">
                <h3 className="mb-3 font-display text-lg font-semibold">{t('report.recommendations')}</h3>
                <div className="space-y-2">
                  {recommendations.map((rec) => (
                    <div key={rec.id} className="rounded-2xl border border-line bg-panel p-4">
                      <p className="text-sm">{rec.content}</p>
                      <div className="mt-2">
                        <FeedbackButtons
                          insight={rec}
                          onFeedback={(value) => sendFeedback(rec, value)}
                        />
                      </div>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-xs text-ink-faint">{t('report.recoNote')}</p>
              </div>
            )}
          </>
        )}

        {tab === 'money' && <FinanceSection streamId={report.id} />}

        {tab === 'topics' &&
          topics.map((topic) => (
            <TopicRow
              key={topic.id}
              streamId={report.id}
              insight={topic}
              onFeedback={(value) => sendFeedback(topic, value)}
            />
          ))}

        {tab === 'chat' && (
          <>
            <CommunitySection streamId={report.id} events={timeline?.events ?? []} />
            <ChattersSection streamId={report.id} />
          </>
        )}
      </div>

      {!summary && topics.length === 0 && peakInsights.size === 0 && (
        <p className="text-sm text-ink-muted">{t('report.noInsights')}</p>
      )}
    </div>
  )
}
