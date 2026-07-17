import { formatTime } from '../api'
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
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Retenção</p>
      <p className="text-sm">
        Você segurou <b className={color}>{retention.retained_pct}%</b> do seu pico de audiência
        (de {retention.peak_viewers} para {retention.final_viewers} viewers).
      </p>
      {retention.biggest_drop_at && (
        <p className="mt-1 text-xs text-zinc-500">
          Maior queda por volta de {formatTime(retention.biggest_drop_at)}.
        </p>
      )}
    </div>
  )
}

function DipContext({ dip }: { dip: ViewerDip }) {
  return (
    <div className="mt-1 space-y-0.5 text-xs text-zinc-500">
      {dip.cause && <p className="text-amber-400/90">provável causa: {dip.cause}</p>}
      {dip.speech_context && (
        <p>
          você falava: "{dip.speech_context.slice(0, 80)}
          {dip.speech_context.length > 80 ? '…' : ''}"
        </p>
      )}
      {!dip.speech_context && dip.scene && <p>no ar: {dip.scene}</p>}
      {dip.chat_context.length > 0 && (
        <p className="text-zinc-600">
          chat: {dip.chat_context.map((line) => line.slice(0, 60)).join(' · ')}
        </p>
      )}
      {dip.recovered_to !== null ? (
        <p className="text-emerald-500/80">
          voltou a {dip.recovered_to} viewers
          {dip.recovered_in_minutes !== null && ` em ${dip.recovered_in_minutes} min`}
        </p>
      ) : (
        <p className="text-zinc-600">não recuperou nos minutos seguintes</p>
      )}
    </div>
  )
}

function Dips({ actionable }: { actionable: ActionableOut }) {
  if (actionable.dips.length === 0) return null
  return (
    <div className="rounded-lg border border-red-900/60 bg-zinc-900 p-4">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-red-400">
        Onde você perdeu audiência
      </p>
      <div className="space-y-3 text-sm">
        {actionable.dips.map((dip) => (
          <div key={dip.at}>
            <span className="tabular-nums text-zinc-400">{formatTime(dip.at)}</span>{' '}
            <span className="font-mono text-[11px] text-zinc-600">({dip.offset_label})</span> ·{' '}
            <span className="text-red-400">−{dip.pct_drop}%</span>{' '}
            <span className="text-zinc-500">
              ({dip.viewers_before} → {dip.viewers_after} viewers, {dip.viewers_delta})
            </span>
            <DipContext dip={dip} />
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-zinc-600">
        O tempo entre parênteses é o offset no VOD, para achar o momento.
      </p>
    </div>
  )
}

function Clips({ actionable }: { actionable: ActionableOut }) {
  if (actionable.clips.length === 0) return null
  return (
    <div className="rounded-lg border border-orange-900/60 bg-zinc-900 p-4">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-orange-400">
        Melhores momentos para clipar
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
            <span className="text-xs text-zinc-500">chat {clip.score.toFixed(1)}x o normal</span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-zinc-600">
        O tempo (ex.: 2m05s) é o offset desde o início da live, para achar o momento no VOD.
      </p>
    </div>
  )
}

function UnansweredQuestions({ actionable }: { actionable: ActionableOut }) {
  if (actionable.unanswered_questions_count === 0) return null
  return (
    <div className="rounded-lg border border-sky-900/60 bg-zinc-900 p-4">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-sky-400">
        {actionable.unanswered_questions_count} pergunta
        {actionable.unanswered_questions_count > 1 ? 's' : ''} do chat sem resposta
      </p>
      <div className="space-y-1 text-sm">
        {actionable.unanswered_questions.map((question, index) => (
          <p key={index}>
            <span className="tabular-nums text-zinc-500">{formatTime(question.sent_at)}</span>{' '}
            <span className="text-purple-400">{question.author_login}:</span> {question.text}
          </p>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-zinc-600">
        Perguntas feitas quando você não estava falando (heurística).
      </p>
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
      <h3 className="mb-3 text-lg font-bold">O que melhorar</h3>
      <div className="grid gap-3 md:grid-cols-2">
        <Retention actionable={actionable} />
        <Dips actionable={actionable} />
        <Clips actionable={actionable} />
        <UnansweredQuestions actionable={actionable} />
      </div>
    </div>
  )
}
