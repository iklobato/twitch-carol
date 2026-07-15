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
import type { FollowerProfile, FollowersOverview, GrowthBucket } from '../types'

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
          <GrowthChart growth={overview.growth} />
          <Composition overview={overview} />
          <ProfileGrid
            title="Streamers que te seguem"
            subtitle="Afiliados e parceiros na sua base: candidatos a collab."
            profiles={overview.notable}
          />
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
