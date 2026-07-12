import type { QueueItem } from '../types'

type StepState = 'done' | 'active' | 'queued' | 'todo' | 'failed'

const STEPS = [
  { label: 'Captura', starts: 'começa: stream.online', ends: 'termina: stream.offline' },
  { label: 'Transcrição', starts: 'depende: áudio no storage', ends: 'termina: segmentos gravados' },
  { label: 'Análise', starts: 'depende: transcrição pronta', ends: 'termina: insights validados' },
  { label: 'Relatório', starts: '', ends: '' },
]

const STATUS_TO_STEP: Record<string, { index: number; state: StepState }> = {
  capturing: { index: 0, state: 'active' },
  queued_transcription: { index: 1, state: 'queued' },
  transcribing: { index: 1, state: 'active' },
  queued_analysis: { index: 2, state: 'queued' },
  analyzing: { index: 2, state: 'active' },
  ready: { index: 3, state: 'done' },
  failed: { index: 3, state: 'failed' },
}

function dotClass(state: StepState): string {
  if (state === 'done') return 'bg-emerald-500 border-emerald-500'
  if (state === 'active') return 'animate-pulse bg-purple-500 border-purple-400'
  if (state === 'queued') return 'bg-amber-500/30 border-amber-500'
  if (state === 'failed') return 'bg-red-600 border-red-500'
  return 'bg-zinc-800 border-zinc-700'
}

export default function PipelineStepper({
  status,
  queue,
}: {
  status: string
  queue: QueueItem | null
}) {
  const current = STATUS_TO_STEP[status] ?? STATUS_TO_STEP.ready
  if (status === 'ready') return null

  function stateFor(index: number): StepState {
    if (status === 'failed') return index < current.index ? 'done' : 'failed'
    if (index < current.index) return 'done'
    if (index === current.index) return current.state
    return 'todo'
  }

  return (
    <div className="mb-6 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <div className="mb-1 flex items-center gap-2">
        {status !== 'failed' ? (
          <>
            <span className="h-2 w-2 animate-pulse rounded-full bg-purple-400" />
            <p className="text-sm font-semibold">Live em processamento</p>
          </>
        ) : (
          <p className="text-sm font-semibold text-red-400">Processamento falhou</p>
        )}
      </div>
      <div className="flex flex-col gap-3 pt-2 md:flex-row md:items-start md:gap-0">
        {STEPS.map((step, index) => {
          const state = stateFor(index)
          const isQueuedHere = state === 'queued' && queue != null
          return (
            <div key={step.label} className="flex flex-1 items-start gap-3 md:flex-col md:gap-2">
              <div className="flex items-center md:w-full">
                <span className={`h-3.5 w-3.5 shrink-0 rounded-full border-2 ${dotClass(state)}`} />
                {index < STEPS.length - 1 && (
                  <span
                    className={`hidden h-0.5 flex-1 md:block ${state === 'done' ? 'bg-emerald-600' : 'bg-zinc-800'}`}
                  />
                )}
              </div>
              <div className="min-w-0 md:pr-4">
                <p
                  className={`text-sm font-semibold ${state === 'active' ? 'text-purple-300' : state === 'done' ? 'text-emerald-400' : state === 'failed' ? 'text-red-400' : 'text-zinc-400'}`}
                >
                  {step.label}
                  {state === 'queued' && ' · na fila'}
                </p>
                {step.starts && <p className="text-xs text-zinc-600">{step.starts}</p>}
                {step.ends && <p className="text-xs text-zinc-600">{step.ends}</p>}
                {isQueuedHere && queue && (
                  <p className="mt-1 text-xs text-amber-400">
                    posição {queue.position}
                    {queue.eta_seconds != null &&
                      ` · ~${Math.max(1, Math.round(queue.eta_seconds / 60))} min`}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
