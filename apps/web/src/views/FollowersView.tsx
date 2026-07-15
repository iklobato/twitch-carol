import {
  BarController,
  BarElement,
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
import { apiGet, formatDate } from '../api'
import type {
  CohortRow,
  CollabCandidate,
  FollowerAi,
  FollowerProfile,
  FollowersOverview,
  FollowerSignals,
  FunnelStage,
  GrowthBucket,
  TopFollower,
  VelocityDay,
} from '../types'

Chart.register(
  LineController,
  LineElement,
  PointElement,
  BarController,
  BarElement,
  CategoryScale,
  LinearScale,
  Filler,
  Tooltip,
  Legend,
)

const TYPE_BADGE: Record<string, string> = {
  affiliate: 'Afiliado',
  partner: 'Parceiro',
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="text-xl font-bold">{value}</p>
      {hint && <p className="text-[11px] text-zinc-600">{hint}</p>}
    </div>
  )
}

function Kpis({ overview }: { overview: FollowersOverview }) {
  const { kpis } = overview
  const age =
    kpis.avg_account_age_days === null
      ? '-'
      : `${(kpis.avg_account_age_days / 365).toFixed(1)} anos`
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
      <StatCard label="Seguidores" value={kpis.total.toLocaleString('pt-BR')} />
      <StatCard
        label="Streamers"
        value={kpis.streamers.toLocaleString('pt-BR')}
        hint={`${kpis.affiliates} afiliados · ${kpis.partners} parceiros`}
      />
      <StatCard label="Novos (7d)" value={kpis.new_7d.toLocaleString('pt-BR')} />
      <StatCard label="Novos (30d)" value={kpis.new_30d.toLocaleString('pt-BR')} />
      <StatCard label="Idade média da conta" value={age} />
    </div>
  )
}

function GrowthChart({ growth }: { growth: GrowthBucket[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const chartRef = useRef<Chart | null>(null)

  useEffect(() => {
    if (!canvasRef.current || growth.length === 0) return
    chartRef.current?.destroy()
    chartRef.current = new Chart(canvasRef.current, {
      data: {
        labels: growth.map((point) => point.month),
        datasets: [
          {
            type: 'line',
            label: 'Total acumulado',
            data: growth.map((point) => point.cumulative),
            borderColor: '#a855f7',
            backgroundColor: 'rgba(168, 85, 247, 0.12)',
            fill: 'origin',
            tension: 0.3,
            yAxisID: 'y',
          },
          {
            type: 'bar',
            label: 'Novos no mês',
            data: growth.map((point) => point.gained),
            backgroundColor: '#34d399',
            yAxisID: 'y1',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#d4d4d8' } } },
        scales: {
          x: { ticks: { color: '#71717a', maxTicksLimit: 12 }, grid: { color: '#27272a' } },
          y: {
            title: { display: true, text: 'acumulado', color: '#71717a' },
            ticks: { color: '#71717a' },
            grid: { color: '#27272a' },
          },
          y1: {
            position: 'right',
            title: { display: true, text: 'novos/mês', color: '#71717a' },
            ticks: { color: '#71717a' },
            grid: { drawOnChartArea: false },
          },
        },
      },
    })
    return () => chartRef.current?.destroy()
  }, [growth])

  if (growth.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Crescimento da base</h3>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        <div className="h-72 w-full">
          <canvas ref={canvasRef} />
        </div>
      </div>
    </div>
  )
}

function ProfileCard({ profile }: { profile: FollowerProfile }) {
  const badge = profile.broadcaster_type ? TYPE_BADGE[profile.broadcaster_type] : null
  return (
    <div className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900 p-3">
      {profile.profile_image_url ? (
        <img
          src={profile.profile_image_url}
          alt={profile.login}
          className="h-10 w-10 shrink-0 rounded-full"
        />
      ) : (
        <div className="h-10 w-10 shrink-0 rounded-full bg-zinc-800" />
      )}
      <div className="min-w-0 flex-1">
        <a
          href={`https://twitch.tv/${profile.login}`}
          target="_blank"
          rel="noreferrer"
          className="block truncate text-sm font-semibold text-purple-300 hover:underline"
        >
          {profile.display_name ?? profile.login}
        </a>
        <p className="truncate text-xs text-zinc-500">
          seguiu {formatDate(profile.followed_at)}
        </p>
      </div>
      {badge && (
        <span className="shrink-0 rounded-full border border-pink-800 px-2 py-0.5 text-[10px] text-pink-300">
          {badge}
        </span>
      )}
    </div>
  )
}

function ProfileGrid({
  title,
  subtitle,
  profiles,
}: {
  title: string
  subtitle: string
  profiles: FollowerProfile[]
}) {
  if (profiles.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">{title}</h3>
      <p className="mb-3 text-sm text-zinc-500">{subtitle}</p>
      <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        {profiles.map((profile) => (
          <ProfileCard key={profile.login} profile={profile} />
        ))}
      </div>
    </div>
  )
}

function Bars({ rows, color }: { rows: { label: string; count: number }[]; color: string }) {
  const max = Math.max(...rows.map((row) => row.count), 1)
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.label} className="flex items-center gap-3 text-sm">
          <span className="w-28 shrink-0 text-zinc-300">{row.label}</span>
          <div className="h-3 flex-1 overflow-hidden rounded bg-zinc-800">
            <div
              className={`h-full rounded ${color}`}
              style={{ width: `${(row.count / max) * 100}%` }}
            />
          </div>
          <span className="w-12 shrink-0 text-right tabular-nums text-zinc-400">
            {row.count.toLocaleString('pt-BR')}
          </span>
        </div>
      ))}
    </div>
  )
}

function Composition({ overview }: { overview: FollowersOverview }) {
  const { by_type, by_age, silent, chatty } = overview.composition
  const engaged = silent + chatty
  const chattyPct = engaged > 0 ? Math.round((chatty / engaged) * 100) : 0
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Composição da base</h3>
      <div className="grid gap-4 md:grid-cols-2">
        {by_type.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Por tipo de conta
            </p>
            <Bars rows={by_type} color="bg-sky-500" />
          </div>
        )}
        {by_age.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Idade das contas
            </p>
            <Bars rows={by_age} color="bg-purple-500" />
          </div>
        )}
      </div>
      <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
          Engajamento no chat
        </p>
        <p className="text-sm text-zinc-400">
          <span className="font-bold text-emerald-400">{chattyPct}%</span> dos seguidores já
          escreveram no chat ({chatty.toLocaleString('pt-BR')} de{' '}
          {engaged.toLocaleString('pt-BR')}). O resto ({silent.toLocaleString('pt-BR')}) só
          observa.
        </p>
      </div>
    </div>
  )
}

function Recommendations({ overview }: { overview: FollowersOverview }) {
  const recs = overview.recommendations
  if (recs.length === 0) return null
  return (
    <div className="mb-6 rounded-lg border border-purple-900/60 bg-purple-950/20 p-4">
      <h3 className="mb-1 text-lg font-bold">Decisões sobre seus seguidores (IA)</h3>
      <p className="mb-3 text-xs text-zinc-500">
        Geradas a partir dos seus números, atualizadas quando uma live é analisada.
      </p>
      <div className="space-y-3">
        {recs.map((rec, index) => (
          <div key={index} className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
            <p className="text-sm">{rec.content}</p>
            {rec.facts.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-xs text-zinc-500">
                {rec.facts.map((fact, i) => (
                  <li key={i}>{fact.replace(/^\[\d+\]\s*/, '↳ ')}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function usd(value: number): string {
  return value.toLocaleString('pt-BR', { style: 'currency', currency: 'USD' })
}

const STAGE_STYLE: Record<string, string> = {
  seguidor: 'border-zinc-700 text-zinc-400',
  engajado: 'border-sky-800 text-sky-300',
  inscrito: 'border-purple-800 text-purple-300',
  pagante: 'border-emerald-800 text-emerald-300',
}

function StageBadge({ stage }: { stage: string }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[10px] ${STAGE_STYLE[stage] ?? 'border-zinc-700 text-zinc-400'}`}
    >
      {stage}
    </span>
  )
}

function Funnel({ funnel }: { funnel: FunnelStage[] }) {
  if (funnel.length === 0) return null
  const top = funnel[0].count || 1
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">Funil de conversão</h3>
      <p className="mb-3 text-sm text-zinc-500">
        De seguidor a pagante. Cada etapa inclui as mais profundas.
      </p>
      <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        {funnel.map((stage) => {
          const pct = Math.round((stage.count / top) * 100)
          return (
            <div key={stage.stage} className="flex items-center gap-3 text-sm">
              <span className="w-40 shrink-0 text-zinc-300">{stage.label}</span>
              <div className="h-4 flex-1 overflow-hidden rounded bg-zinc-800">
                <div
                  className="h-full rounded bg-gradient-to-r from-sky-600 to-emerald-500"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="w-24 shrink-0 text-right tabular-nums text-zinc-400">
                {stage.count.toLocaleString('pt-BR')} · {pct}%
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Cohorts({ cohorts }: { cohorts: CohortRow[] }) {
  if (cohorts.length === 0) return null
  const recent = cohorts.slice(-12).reverse()
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">Retenção por safra</h3>
      <p className="mb-3 text-sm text-zinc-500">
        Para cada mês em que ganhou seguidores, quantos depois deram chat, assinaram ou
        pagaram.
      </p>
      <div className="overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-900">
        <table className="w-full min-w-[32rem] text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-left text-xs uppercase tracking-wide text-zinc-500">
              <th className="p-3">Mês</th>
              <th className="p-3 text-right">Seguidores</th>
              <th className="p-3 text-right">Deram chat</th>
              <th className="p-3 text-right">Assinaram</th>
              <th className="p-3 text-right">Pagaram</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((row) => (
              <tr key={row.month} className="border-b border-zinc-800/50 last:border-0">
                <td className="p-3 text-zinc-300">{row.month}</td>
                <td className="p-3 text-right tabular-nums">{row.size}</td>
                <td className="p-3 text-right tabular-nums text-sky-300">
                  {row.chatted} <span className="text-zinc-600">({Math.round((row.chatted / row.size) * 100)}%)</span>
                </td>
                <td className="p-3 text-right tabular-nums text-purple-300">{row.subscribed}</td>
                <td className="p-3 text-right tabular-nums text-emerald-300">{row.paid}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function FollowerTable({
  title,
  subtitle,
  rows,
  valueColumn,
}: {
  title: string
  subtitle: string
  rows: TopFollower[]
  valueColumn: 'usd' | 'months'
}) {
  if (rows.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">{title}</h3>
      <p className="mb-3 text-sm text-zinc-500">{subtitle}</p>
      <div className="space-y-2">
        {rows.map((row, index) => (
          <div
            key={row.login}
            className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900 p-3"
          >
            <span className="w-6 shrink-0 text-sm font-bold tabular-nums text-zinc-600">
              {index + 1}º
            </span>
            <a
              href={`https://twitch.tv/${row.login}`}
              target="_blank"
              rel="noreferrer"
              className="min-w-32 text-sm font-semibold text-purple-300 hover:underline"
            >
              {row.display_name ?? row.login}
            </a>
            <StageBadge stage={row.stage} />
            <span className="ml-auto text-sm tabular-nums">
              {valueColumn === 'usd' ? (
                <span className="font-semibold text-emerald-400">{usd(row.estimated_usd)}</span>
              ) : (
                <span className="font-semibold text-purple-300">
                  {row.sub_months} {row.sub_months === 1 ? 'mês' : 'meses'}
                </span>
              )}
            </span>
            <span className="w-full text-xs text-zinc-500 md:w-auto md:pl-2">
              {row.messages.toLocaleString('pt-BR')} msgs · {row.streams_present} live
              {row.streams_present === 1 ? '' : 's'}
              {row.last_seen && <> · visto {formatDate(row.last_seen)}</>}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function VelocitySparkline({ velocity }: { velocity: VelocityDay[] }) {
  if (velocity.length === 0) return null
  const recent = velocity.slice(-60)
  const max = Math.max(...recent.map((d) => d.follows), 1)
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Velocidade de follows (barras vermelhas = picos anômalos)
      </p>
      <div className="flex h-24 items-end gap-0.5">
        {recent.map((day) => (
          <div
            key={day.day}
            title={`${day.day}: ${day.follows} follows${day.is_spike ? ' (pico)' : ''}`}
            className={`flex-1 rounded-t ${day.is_spike ? 'bg-red-500' : 'bg-sky-600'}`}
            style={{ height: `${Math.max((day.follows / max) * 100, 2)}%` }}
          />
        ))}
      </div>
    </div>
  )
}

function Signals({ signals }: { signals: FollowerSignals }) {
  const { raids, suspicious, suspicious_total, velocity, topic_follows } = signals
  const hasAny =
    raids.length > 0 ||
    suspicious.length > 0 ||
    velocity.length > 0 ||
    topic_follows.length > 0
  if (!hasAny) return null
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">De onde vêm e o que é real</h3>
      <div className="mb-3">
        <VelocitySparkline velocity={velocity} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {raids.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Raids que trouxeram seguidores
            </p>
            <div className="space-y-1.5 text-sm">
              {raids.slice(0, 6).map((raid, i) => (
                <div key={i} className="flex items-center justify-between">
                  <span className="text-purple-300">
                    {raid.raider_login ?? 'raid'} <span className="text-zinc-600">· {raid.viewers} viewers</span>
                  </span>
                  <span className="text-emerald-400">+{raid.follows_after} follows</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {topic_follows.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Assuntos que geraram follows
            </p>
            <div className="space-y-1.5 text-sm">
              {topic_follows.slice(0, 6).map((t, i) => (
                <div key={i} className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate">{t.topic}</span>
                  <span className="shrink-0 text-emerald-400">+{t.follows}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      {suspicious.length > 0 && (
        <div className="mt-4 rounded-lg border border-red-900/50 bg-red-950/20 p-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-red-400">
            Follows suspeitos ({suspicious_total})
          </p>
          <p className="mb-3 text-xs text-zinc-500">
            Perfis com sinais de bot/fake (conta nova, sem foto/bio, seguiu logo após criar).
          </p>
          <div className="flex flex-wrap gap-2">
            {suspicious.slice(0, 18).map((s) => (
              <span
                key={s.login}
                title={s.reasons.join(', ')}
                className="rounded-full border border-red-800 px-3 py-1 text-xs text-red-200"
              >
                {s.display_name ?? s.login} <span className="text-red-400">· {s.score}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const SEGMENT_COLOR: Record<string, string> = {
  streamers: 'border-pink-800 bg-pink-950/20',
  paying_fans: 'border-emerald-800 bg-emerald-950/20',
  dormant: 'border-amber-800 bg-amber-950/20',
  engaged: 'border-sky-800 bg-sky-950/20',
  newcomers: 'border-purple-800 bg-purple-950/20',
  lurkers: 'border-zinc-800 bg-zinc-900',
}

function AiSection({ ai }: { ai: FollowerAi }) {
  const { segments, audience_summary, reactivations } = ai
  if (segments.length === 0 && !audience_summary && reactivations.length === 0)
    return null
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">Personas e decisões (IA)</h3>
      <p className="mb-3 text-sm text-zinc-500">
        A base agrupada em personas. Ações e mensagens são geradas quando uma live é
        analisada.
      </p>

      {audience_summary && (
        <div className="mb-4 rounded-lg border border-purple-900/60 bg-purple-950/20 p-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-purple-300">
            Quem te segue
          </p>
          <p className="text-sm">{audience_summary}</p>
        </div>
      )}

      {segments.length > 0 && (
        <div className="mb-4 grid gap-3 md:grid-cols-2">
          {segments.map((seg) => (
            <div
              key={seg.key}
              className={`rounded-lg border p-4 ${SEGMENT_COLOR[seg.key] ?? 'border-zinc-800 bg-zinc-900'}`}
            >
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="font-semibold">{seg.label}</span>
                <span className="tabular-nums text-zinc-400">
                  {seg.count.toLocaleString('pt-BR')}
                </span>
              </div>
              <p className="mb-2 text-xs text-zinc-500">{seg.description}</p>
              {seg.examples.length > 0 && (
                <p className="mb-2 truncate text-xs text-zinc-600">
                  ex: {seg.examples.join(', ')}
                </p>
              )}
              {seg.action && (
                <p className="rounded bg-black/30 p-2 text-sm text-zinc-200">
                  → {seg.action}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {reactivations.length > 0 && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/10 p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-amber-400">
            Trazer de volta (mensagens sugeridas)
          </p>
          <div className="space-y-3">
            {reactivations.map((r, i) => (
              <div key={i} className="text-sm">
                <span className="font-semibold text-purple-300">{r.who}</span>
                <p className="mt-0.5 rounded bg-black/30 p-2 text-zinc-200">{r.message}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function CollabSection({ collab }: { collab: CollabCandidate[] }) {
  if (collab.length === 0) return null
  const shared = collab.filter((c) => c.shared_category).length
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">Candidatos a collab</h3>
      <p className="mb-3 text-sm text-zinc-500">
        Streamers que te seguem, com o que transmitem.{' '}
        {shared > 0 && (
          <span className="text-emerald-400">
            {shared} jogam a mesma categoria que você.
          </span>
        )}
      </p>
      <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        {collab.map((c) => (
          <div
            key={c.login}
            className={`flex items-center gap-3 rounded-lg border p-3 ${c.shared_category ? 'border-emerald-800 bg-emerald-950/20' : 'border-zinc-800 bg-zinc-900'}`}
          >
            {c.profile_image_url ? (
              <img
                src={c.profile_image_url}
                alt={c.login}
                className="h-10 w-10 shrink-0 rounded-full"
              />
            ) : (
              <div className="h-10 w-10 shrink-0 rounded-full bg-zinc-800" />
            )}
            <div className="min-w-0 flex-1">
              <a
                href={`https://twitch.tv/${c.login}`}
                target="_blank"
                rel="noreferrer"
                className="block truncate text-sm font-semibold text-purple-300 hover:underline"
              >
                {c.display_name ?? c.login}
              </a>
              <p className="truncate text-xs text-zinc-500">
                {c.stream_category ?? 'categoria desconhecida'}
                {c.stream_language && ` · ${c.stream_language}`}
              </p>
            </div>
            {c.shared_category && (
              <span className="shrink-0 rounded-full border border-emerald-700 px-2 py-0.5 text-[10px] text-emerald-300">
                mesma categoria
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function FollowersView() {
  const [overview, setOverview] = useState<FollowersOverview | null>(null)

  useEffect(() => {
    apiGet<FollowersOverview>('/api/followers').then(setOverview)
  }, [])

  if (overview === null)
    return <p className="text-zinc-400">Carregando seus seguidores...</p>

  return (
    <div>
      <a href="#/" className="text-sm text-zinc-400 hover:text-zinc-200">
        ← voltar
      </a>
      <h2 className="mb-4 mt-2 text-xl font-bold">Meus seguidores</h2>
      {overview.kpis.total === 0 ? (
        <p className="text-zinc-400">
          Nenhum seguidor importado ainda. Reconecte sua conta para o StreamIntel puxar e
          enriquecer sua base de seguidores da Twitch.
        </p>
      ) : (
        <>
          <Kpis overview={overview} />
          <Recommendations overview={overview} />
          <AiSection ai={overview.ai} />
          <Funnel funnel={overview.funnel} />
          <GrowthChart growth={overview.growth} />
          <Signals signals={overview.signals} />
          <Composition overview={overview} />
          <FollowerTable
            title="Quem mais contribuiu"
            subtitle="Seguidores que mais trouxeram receita (bits, subs, gifts)."
            rows={overview.top_value}
            valueColumn="usd"
          />
          <FollowerTable
            title="Assinantes mais leais"
            subtitle="Maior tempo de inscrição contínua."
            rows={overview.loyal_subscribers}
            valueColumn="months"
          />
          <Cohorts cohorts={overview.cohorts} />
          <CollabSection collab={overview.collab} />
          <ProfileGrid
            title="Seguidores recentes"
            subtitle="Quem chegou por último."
            profiles={overview.recent}
          />
        </>
      )}
    </div>
  )
}
