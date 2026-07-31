import { formatTime } from '../api'
import { t } from '../i18n'
import type { ActionableOut, ViewerDip } from '../types'

function Retention({ actionable }: { actionable: ActionableOut }) {
  const retention = actionable.retention
  if (retention === null) return null
  const color =
    retention.retained_pct >= 70
      ? 'text-emerald-400'
      : retention.retained_pct >= 40
        ? 'text-amber-400'
        : 'text-red-400'
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        {t('actionable.retention')}
      </p>
      <p className="text-sm">
        {t('actionable.retention.youKept')}{' '}
        <b className={color}>{retention.retained_pct}%</b>{' '}
        {t('actionable.retention.ofPeak', {
          peak: retention.peak_viewers,
          final: retention.final_viewers,
        })}
      </p>
      {retention.biggest_drop_at && (
        <p className="mt-1 text-xs text-zinc-500">
          {t('actionable.retention.biggestDrop', {
            time: formatTime(retention.biggest_drop_at),
          })}
        </p>
      )}
    </div>
  )
}

function DipContext({ dip }: { dip: ViewerDip }) {
  return (
    <div className="mt-1 space-y-0.5 text-xs text-zinc-500">
      {dip.cause && (
        <p className="text-amber-400/90">{t('actionable.dip.cause', { cause: dip.cause })}</p>
      )}
      {dip.speech_context && (
        <p>
          {t('actionable.dip.speech', {
            text: dip.speech_context.slice(0, 80) + (dip.speech_context.length > 80 ? '…' : ''),
          })}
        </p>
      )}
      {!dip.speech_context && dip.scene && <p>{t('actionable.dip.scene', { scene: dip.scene })}</p>}
      {dip.chat_context.length > 0 && (
        <p className="text-zinc-600">
          {t('actionable.dip.chat', {
            lines: dip.chat_context.map((line) => line.slice(0, 60)).join(' · '),
          })}
        </p>
      )}
      {dip.recovered_to !== null ? (
        <p className="text-emerald-500/80">
          {t('actionable.dip.recovered', { n: dip.recovered_to })}
          {dip.recovered_in_minutes !== null &&
            t('actionable.dip.recoveredIn', { n: dip.recovered_in_minutes })}
        </p>
      ) : (
        <p className="text-zinc-600">{t('actionable.dip.notRecovered')}</p>
      )}
    </div>
  )
}

function Dips({ actionable }: { actionable: ActionableOut }) {
  if (actionable.dips.length === 0) return null
  return (
    <div className="rounded-lg border border-red-900/60 bg-zinc-900 p-4">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-red-400">
        {t('actionable.dips.title')}
      </p>
      <div className="space-y-3 text-sm">
        {actionable.dips.map((dip) => (
          <div key={dip.at}>
            <span className="tabular-nums text-zinc-400">{formatTime(dip.at)}</span>{' '}
            <span className="font-mono text-[11px] text-zinc-600">({dip.offset_label})</span> ·{' '}
            <span className="text-red-400">−{dip.pct_drop}%</span>{' '}
            <span className="text-zinc-500">
              {t('actionable.dips.viewers', {
                before: dip.viewers_before,
                after: dip.viewers_after,
                delta: dip.viewers_delta,
              })}
            </span>
            <DipContext dip={dip} />
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-zinc-600">{t('actionable.dips.note')}</p>
    </div>
  )
}

function Clips({ actionable }: { actionable: ActionableOut }) {
  if (actionable.clips.length === 0) return null
  return (
    <div className="rounded-lg border border-orange-900/60 bg-zinc-900 p-4">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-orange-400">
        {t('actionable.clips.title')}
      </p>
      <div className="space-y-1.5 text-sm">
        {actionable.clips.map((clip) => (
          <div key={clip.offset_seconds} className="flex items-center gap-2">
            <span className="rounded bg-zinc-800 px-2 py-0.5 font-mono text-xs text-orange-300">
              {clip.offset_label}
            </span>
            <span className="text-zinc-400">
              {formatTime(clip.window_start)}–{formatTime(clip.window_end)}
            </span>
            <span className="text-xs text-zinc-500">
              {t('actionable.clips.score', { score: clip.score.toFixed(1) })}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-zinc-600">{t('actionable.clips.note')}</p>
    </div>
  )
}

function UnansweredQuestions({ actionable }: { actionable: ActionableOut }) {
  const count = actionable.unanswered_questions_count
  if (count === 0) return null
  return (
    <div className="rounded-lg border border-sky-900/60 bg-zinc-900 p-4">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-sky-400">
        {t(count > 1 ? 'actionable.questions.titlePlural' : 'actionable.questions.title', {
          n: count,
        })}
      </p>
      <div className="space-y-1 text-sm">
        {actionable.unanswered_questions.map((question, index) => (
          <p key={index}>
            <span className="tabular-nums text-zinc-500">{formatTime(question.sent_at)}</span>{' '}
            <span className="text-purple-400">{question.author_login}:</span> {question.text}
          </p>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-zinc-600">{t('actionable.questions.note')}</p>
    </div>
  )
}

export default function ActionableSection({ actionable }: { actionable: ActionableOut | null }) {
  if (actionable === null) return null
  const hasContent =
    actionable.retention !== null ||
    actionable.dips.length > 0 ||
    actionable.clips.length > 0 ||
    actionable.unanswered_questions_count > 0
  if (!hasContent) return null

  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">{t('actionable.title')}</h3>
      <div className="grid gap-3 md:grid-cols-2">
        <Retention actionable={actionable} />
        <Dips actionable={actionable} />
        <Clips actionable={actionable} />
        <UnansweredQuestions actionable={actionable} />
      </div>
    </div>
  )
}
