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
import { apiGet, formatDate } from '../api'
import type { ChannelOverview, GrowthPoint } from '../types'

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

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="text-xl font-bold">{value}</p>
    </div>
  )
}

function LoyalChatters({ overview }: { overview: ChannelOverview }) {
  if (overview.loyal_chatters.length === 0) return null
  const maxStreams = overview.loyal_chatters[0].streams_attended
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">Seus mais fiéis</h3>
      <p className="mb-3 text-sm text-zinc-500">
        Ordenados por número de lives em que apareceram no chat.
      </p>
      <div className="space-y-2">
        {overview.loyal_chatters.map((chatter, index) => (
          <div
            key={chatter.author_login}
            className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900 p-3"
          >
            <span className="w-6 shrink-0 text-sm font-bold tabular-nums text-zinc-600">
              {index + 1}º
            </span>
            <span className="min-w-32 text-sm font-semibold text-purple-300">
              {chatter.author_login}
            </span>
            <div className="hidden w-32 md:block">
              <div className="h-2 overflow-hidden rounded bg-zinc-800">
                <div
                  className="h-full rounded bg-purple-500"
                  style={{ width: `${(chatter.streams_attended / maxStreams) * 100}%` }}
                />
              </div>
            </div>
            <span className="text-xs tabular-nums text-zinc-400">
              {chatter.streams_attended} live{chatter.streams_attended > 1 ? 's' : ''} ·{' '}
              {chatter.total_messages.toLocaleString('pt-BR')} msgs · visto por último{' '}
              {formatDate(chatter.last_seen)}
            </span>
            {chatter.followed && (
              <span className="rounded-full border border-emerald-800 px-2 py-0.5 text-[10px] text-emerald-400">
                seguidor
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function BestWeekdays({ overview }: { overview: ChannelOverview }) {
  if (overview.best_weekdays.length === 0) return null
  const max = Math.max(...overview.best_weekdays.map((slot) => slot.avg_peak_viewers), 1)
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">Melhores dias para transmitir</h3>
      <p className="mb-3 text-sm text-zinc-500">Média de pico de viewers por dia da semana.</p>
      <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        {overview.best_weekdays.map((slot) => (
          <div key={slot.weekday} className="flex items-center gap-3">
            <span className="w-20 shrink-0 text-sm text-zinc-300">{slot.label}</span>
            <div className="h-4 flex-1 overflow-hidden rounded bg-zinc-800">
              <div
                className="h-full rounded bg-sky-500"
                style={{ width: `${(slot.avg_peak_viewers / max) * 100}%` }}
              />
            </div>
            <span className="w-28 shrink-0 text-right text-xs tabular-nums text-zinc-400">
              {slot.avg_peak_viewers} · {slot.streams} live{slot.streams > 1 ? 's' : ''}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function GrowthChart({ growth }: { growth: GrowthPoint[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const chartRef = useRef<Chart | null>(null)

  useEffect(() => {
    if (!canvasRef.current || growth.length === 0) return
    chartRef.current?.destroy()
    chartRef.current = new Chart(canvasRef.current, {
      type: 'line',
      data: {
        labels: growth.map((point) => formatDate(point.started_at)),
        datasets: [
          {
            label: 'Pico de viewers',
            data: growth.map((point) => point.peak_viewers),
            borderColor: '#38bdf8',
            backgroundColor: 'rgba(56, 189, 248, 0.1)',
            fill: 'origin',
            tension: 0.3,
            yAxisID: 'y',
          },
          {
            label: 'Novos seguidores',
            data: growth.map((point) => point.followers_gained),
            borderColor: '#34d399',
            tension: 0.3,
            yAxisID: 'y1',
          },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: '#d4d4d8' } } },
        scales: {
          x: { ticks: { color: '#71717a', maxTicksLimit: 12 }, grid: { color: '#27272a' } },
          y: {
            title: { display: true, text: 'viewers', color: '#71717a' },
            ticks: { color: '#71717a' },
            grid: { color: '#27272a' },
          },
          y1: {
            position: 'right',
            title: { display: true, text: 'seguidores', color: '#71717a' },
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
      <h3 className="mb-3 text-lg font-bold">Crescimento ao longo das lives</h3>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        <canvas ref={canvasRef} className="max-h-72 w-full" />
      </div>
    </div>
  )
}

function RecurringTopics({ overview }: { overview: ChannelOverview }) {
  const recurring = overview.recurring_topics.filter((topic) => topic.streams > 1)
  if (recurring.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">Assuntos que sempre voltam</h3>
      <p className="mb-3 text-sm text-zinc-500">Tópicos que apareceram em mais de uma live.</p>
      <div className="flex flex-wrap gap-2">
        {recurring.map((topic) => (
          <span
            key={topic.name}
            className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-sm"
          >
            {topic.name} <span className="text-zinc-500">· {topic.streams} lives</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function usd(value: number): string {
  return value.toLocaleString('pt-BR', { style: 'currency', currency: 'USD' })
}

function ContentRevenue({ overview }: { overview: ChannelOverview }) {
  const buckets = overview.content_revenue
  if (buckets.length === 0) return null
  const maxPerHour = Math.max(...buckets.map((b) => b.usd_per_hour), 0.01)
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">Conteúdo que converte</h3>
      <p className="mb-3 text-sm text-zinc-500">
        Receita por categoria e por hora transmitida. Faça mais do que rende mais por hora.
      </p>
      <div className="space-y-2 text-sm">
        {buckets.map((bucket) => (
          <div
            key={bucket.category}
            className="rounded-lg border border-zinc-800 bg-zinc-900 p-3"
          >
            <div className="mb-1 flex items-center justify-between">
              <span className="font-semibold">{bucket.category}</span>
              <span className="text-emerald-400">
                {usd(bucket.usd_per_hour)}
                <span className="text-xs text-zinc-500">/h</span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded bg-zinc-800">
              <div
                className="h-full rounded bg-emerald-500"
                style={{ width: `${(bucket.usd_per_hour / maxPerHour) * 100}%` }}
              />
            </div>
            <div className="mt-1 flex justify-between text-xs text-zinc-500">
              <span>
                {bucket.streams} live{bucket.streams > 1 ? 's' : ''} · pico médio{' '}
                {bucket.avg_peak_viewers.toLocaleString('pt-BR')}
              </span>
              <span>{usd(bucket.estimated_usd)} no total</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function RecommendationsSection({ overview }: { overview: ChannelOverview }) {
  const [recs, setRecs] = useState(overview.recommendations)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)

  async function generate() {
    setLoading(true)
    setError(false)
    try {
      const response = await fetch('/api/channel/recommendations', { method: 'POST' })
      if (!response.ok) throw new Error(String(response.status))
      setRecs(await response.json())
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mb-6 rounded-lg border border-purple-900/60 bg-purple-950/20 p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="text-lg font-bold">Como ganhar mais (IA)</h3>
        <button
          onClick={generate}
          disabled={loading}
          className="rounded-md bg-purple-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-purple-500 disabled:opacity-50"
        >
          {loading ? 'Gerando...' : recs.length > 0 ? 'Atualizar' : 'Gerar recomendações'}
        </button>
      </div>
      {error && (
        <p className="mb-2 text-sm text-red-400">
          Não foi possível gerar agora. Tente de novo em instantes.
        </p>
      )}
      {recs.length === 0 && !loading && !error && (
        <p className="text-sm text-zinc-400">
          A IA analisa sua receita, assuntos, contribuintes e engajamento e sugere onde focar
          para monetizar mais. Clique para gerar.
        </p>
      )}
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

const TIER_LABELS: Record<string, string> = {
  '1000': 'Tier 1',
  '2000': 'Tier 2',
  '3000': 'Tier 3',
}

function SubscribersSection({ overview }: { overview: ChannelOverview }) {
  const { total, tiers, gifted_pct, subs_ended, top_bits } = overview.subscribers
  if (total === 0 && top_bits.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Assinantes e bits</h3>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Assinantes ativos
          </p>
          <p className="text-2xl font-bold text-purple-300">{total.toLocaleString('pt-BR')}</p>
          <div className="mt-2 space-y-1 text-sm">
            {tiers.map((t) => (
              <div key={t.tier} className="flex justify-between text-zinc-400">
                <span>{TIER_LABELS[t.tier] ?? t.tier}</span>
                <span>{t.count}</span>
              </div>
            ))}
            <div className="flex justify-between text-zinc-500">
              <span>Presenteados</span>
              <span>{gifted_pct}%</span>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Churn
          </p>
          <p className="text-2xl font-bold text-red-400">{subs_ended}</p>
          <p className="text-xs text-zinc-500">assinaturas encerradas nas lives capturadas</p>
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Top bits (todos os tempos)
          </p>
          {top_bits.length > 0 ? (
            <div className="space-y-1 text-sm">
              {top_bits.slice(0, 5).map((leader, index) => (
                <div key={leader.login} className="flex justify-between">
                  <span>
                    <span className="mr-2 text-zinc-600">{index + 1}º</span>
                    <span className="text-purple-300">{leader.login}</span>
                  </span>
                  <span className="text-zinc-400">
                    {leader.score.toLocaleString('pt-BR')}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-zinc-600">Sem leaderboard (requer afiliação).</p>
          )}
        </div>
      </div>
    </div>
  )
}

const GOAL_LABELS: Record<string, string> = {
  follower: 'Seguidores',
  subscription: 'Inscritos',
  subscription_count: 'Inscritos',
  new_subscription: 'Novos inscritos',
}

function CommunityHealth({ overview }: { overview: ChannelOverview }) {
  const { engaged_viewer_pct, vips, goals } = overview.community
  if (engaged_viewer_pct === null && vips.length === 0 && goals.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Comunidade</h3>
      <div className="grid gap-4 md:grid-cols-3">
        {goals.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 md:col-span-2">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Metas
            </p>
            <div className="space-y-3 text-sm">
              {goals.map((goal) => (
                <div key={goal.goal_type + goal.description}>
                  <div className="mb-1 flex justify-between">
                    <span>{goal.description ?? GOAL_LABELS[goal.goal_type] ?? goal.goal_type}</span>
                    <span className="text-zinc-400">
                      {goal.current_amount.toLocaleString('pt-BR')}/
                      {goal.target_amount.toLocaleString('pt-BR')}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded bg-zinc-800">
                    <div
                      className="h-full rounded bg-purple-500"
                      style={{ width: `${Math.min(goal.pct, 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Engajamento do chat
          </p>
          {engaged_viewer_pct !== null ? (
            <>
              <p className="text-2xl font-bold text-emerald-400">{engaged_viewer_pct}%</p>
              <p className="text-xs text-zinc-500">dos viewers escrevem no chat (o resto observa)</p>
            </>
          ) : (
            <p className="text-sm text-zinc-600">Sem dados de viewers ainda.</p>
          )}
        </div>
      </div>
      {vips.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            VIPs
          </p>
          <div className="flex flex-wrap gap-2">
            {vips.map((vip) => (
              <span
                key={vip}
                className="rounded-full border border-pink-800 bg-pink-950/40 px-3 py-1 text-sm text-pink-200"
              >
                {vip}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function EngagementSection({ overview }: { overview: ChannelOverview }) {
  const { hype_train, top_rewards, ads } = overview.engagement
  if (hype_train.count === 0 && top_rewards.length === 0 && ads.breaks === 0) return null
  const maxRedemptions = Math.max(...top_rewards.map((r) => r.redemptions), 1)
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Engajamento que gera receita</h3>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Hype Trains
          </p>
          {hype_train.count > 0 ? (
            <div className="space-y-1 text-sm">
              <p className="text-2xl font-bold text-purple-300">{hype_train.count}</p>
              <p className="text-zinc-400">Melhor nível: {hype_train.best_level}</p>
              <p className="text-zinc-500">
                {hype_train.total_contributed.toLocaleString('pt-BR')} em contribuições
              </p>
            </div>
          ) : (
            <p className="text-sm text-zinc-600">Nenhum hype train ainda.</p>
          )}
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Recompensas mais resgatadas
          </p>
          {top_rewards.length > 0 ? (
            <div className="space-y-1.5 text-sm">
              {top_rewards.map((reward) => (
                <div key={reward.title} className="flex items-center gap-2">
                  <span className="w-28 shrink-0 truncate" title={reward.title}>
                    {reward.title}
                  </span>
                  <div className="h-2 flex-1 overflow-hidden rounded bg-zinc-800">
                    <div
                      className="h-full rounded bg-purple-500"
                      style={{ width: `${(reward.redemptions / maxRedemptions) * 100}%` }}
                    />
                  </div>
                  <span className="w-8 shrink-0 text-right text-zinc-400">
                    {reward.redemptions}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-zinc-600">Nenhum resgate de pontos ainda.</p>
          )}
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Anúncios
          </p>
          {ads.breaks > 0 ? (
            <div className="space-y-1 text-sm">
              <p className="text-zinc-400">
                {ads.breaks} break{ads.breaks > 1 ? 's' : ''} ·{' '}
                {Math.round(ads.total_seconds / 60)}min de ads
              </p>
              {ads.avg_viewer_change_pct !== null && (
                <p
                  className={
                    ads.avg_viewer_change_pct < 0 ? 'text-red-400' : 'text-emerald-400'
                  }
                >
                  {ads.avg_viewer_change_pct > 0 ? '+' : ''}
                  {ads.avg_viewer_change_pct}% de viewers ao redor dos ads
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-zinc-600">Nenhum ad break capturado.</p>
          )}
        </div>
      </div>
    </div>
  )
}

function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  return hours > 0 ? `${hours}h${minutes.toString().padStart(2, '0')}` : `${minutes}min`
}

function PastBroadcasts({ overview }: { overview: ChannelOverview }) {
  if (overview.past_broadcasts.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">Lives passadas</h3>
      <p className="mb-3 text-sm text-zinc-500">
        VODs da Twitch importadas ao conectar. Views são totais da gravação, não viewers ao vivo.
      </p>
      <div className="space-y-2">
        {overview.past_broadcasts.map((vod) => (
          <a
            key={vod.url}
            href={vod.url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-900 p-3 text-sm hover:border-zinc-600"
          >
            <span className="min-w-0 flex-1 truncate">{vod.title ?? 'Sem título'}</span>
            <span className="shrink-0 text-zinc-500">{formatDate(vod.published_at)}</span>
            <span className="shrink-0 text-zinc-500">{formatDuration(vod.duration_seconds)}</span>
            <span className="w-20 shrink-0 text-right text-zinc-400">
              {vod.view_count.toLocaleString('pt-BR')} views
            </span>
          </a>
        ))}
      </div>
    </div>
  )
}

function ChannelMonetization({ overview }: { overview: ChannelOverview }) {
  const finance = overview.finance
  if (finance.total_estimated_usd === 0 && finance.top_contributors.length === 0) {
    return (
      <div className="mb-6">
        <h3 className="mb-1 text-lg font-bold">Monetização</h3>
        <p className="text-sm text-zinc-500">
          Ainda sem bits ou assinaturas capturados. Aparece aqui quando seu canal começar a
          monetizar (requer parceria/afiliação na Twitch).
        </p>
      </div>
    )
  }
  const maxTopic = Math.max(...finance.top_monetizing_topics.map((t) => t.estimated_usd), 0.01)
  const maxRevenue = Math.max(...overview.growth.map((g) => g.estimated_usd), 0.01)
  const paidStreams = overview.growth.filter((g) => g.estimated_usd > 0)

  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">Monetização (todas as lives)</h3>
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-emerald-900/60 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">Arrecadado (estimado)</p>
          <p className="text-xl font-bold text-emerald-400">{usd(finance.total_estimated_usd)}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">Bits</p>
          <p className="text-xl font-bold">{finance.total_bits.toLocaleString('pt-BR')}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">Assinaturas</p>
          <p className="text-xl font-bold">{finance.total_subs.toLocaleString('pt-BR')}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">Subs presenteados</p>
          <p className="text-xl font-bold">{finance.total_gifts.toLocaleString('pt-BR')}</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {finance.top_contributors.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Quem mais contribuiu
            </p>
            <div className="space-y-1.5 text-sm">
              {finance.top_contributors.map((contributor, index) => (
                <div key={contributor.login} className="flex items-center justify-between">
                  <span>
                    <span className="mr-2 text-zinc-600">{index + 1}º</span>
                    <span className="text-purple-300">{contributor.login}</span>
                    <span className="ml-2 text-xs text-zinc-500">
                      em {contributor.streams} live{contributor.streams > 1 ? 's' : ''}
                    </span>
                  </span>
                  <span className="font-semibold text-emerald-400">{usd(contributor.estimated_usd)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {finance.top_monetizing_topics.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Assuntos que mais monetizam
            </p>
            <div className="space-y-2 text-sm">
              {finance.top_monetizing_topics.map((topic) => (
                <div key={topic.name} className="flex items-center gap-3">
                  <span className="w-36 shrink-0 truncate">{topic.name}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded bg-zinc-800">
                    <div
                      className="h-full rounded bg-emerald-500"
                      style={{ width: `${(topic.estimated_usd / maxTopic) * 100}%` }}
                    />
                  </div>
                  <span className="w-16 shrink-0 text-right text-emerald-400">{usd(topic.estimated_usd)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {paidStreams.length > 0 && (
        <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Receita por live
          </p>
          <div className="space-y-2 text-sm">
            {paidStreams.map((point) => (
              <a
                key={point.stream_id}
                href={`#/stream/${point.stream_id}`}
                className="flex items-center gap-3 hover:text-purple-300"
              >
                <span className="w-48 shrink-0 truncate">{point.title ?? `Live #${point.stream_id}`}</span>
                <div className="h-2 flex-1 overflow-hidden rounded bg-zinc-800">
                  <div
                    className="h-full rounded bg-emerald-500"
                    style={{ width: `${(point.estimated_usd / maxRevenue) * 100}%` }}
                  />
                </div>
                <span className="w-16 shrink-0 text-right text-emerald-400">{usd(point.estimated_usd)}</span>
              </a>
            ))}
          </div>
        </div>
      )}
      <p className="mt-2 text-[11px] text-zinc-600">
        Valores em dólar são estimativas da sua parte (Twitch não divulga o split exato).
      </p>
    </div>
  )
}

export default function ChannelView() {
  const [overview, setOverview] = useState<ChannelOverview | null>(null)

  useEffect(() => {
    apiGet<ChannelOverview>('/api/channel').then(setOverview)
  }, [])

  if (overview === null) return <p className="text-zinc-400">Carregando o resumo do canal...</p>

  if (overview.total_streams === 0) {
    return (
      <div>
        <a href="#/" className="text-sm text-zinc-400 hover:text-zinc-200">
          ← voltar
        </a>
        <h2 className="mb-2 mt-2 text-xl font-bold">Meu canal</h2>
        <p className="text-zinc-400">
          Ainda não há lives finalizadas. Assim que você transmitir, este resumo mostra seus
          fiéis, melhores horários e crescimento.
        </p>
      </div>
    )
  }

  return (
    <div>
      <a href="#/" className="text-sm text-zinc-400 hover:text-zinc-200">
        ← voltar
      </a>
      <h2 className="mb-4 mt-2 text-xl font-bold">Meu canal</h2>
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatCard label="Lives" value={overview.total_streams.toLocaleString('pt-BR')} />
        <StatCard label="Mensagens" value={overview.total_messages.toLocaleString('pt-BR')} />
        <StatCard label="Chatters únicos" value={overview.unique_chatters.toLocaleString('pt-BR')} />
        <StatCard
          label="Seguidores"
          value={overview.total_followers_gained.toLocaleString('pt-BR')}
        />
        <StatCard
          label="Arrecadado (estimado)"
          value={usd(overview.finance.total_estimated_usd)}
        />
      </div>
      <ChannelMonetization overview={overview} />
      <RecommendationsSection overview={overview} />
      <SubscribersSection overview={overview} />
      <ContentRevenue overview={overview} />
      <EngagementSection overview={overview} />
      <CommunityHealth overview={overview} />
      <LoyalChatters overview={overview} />
      <GrowthChart growth={overview.growth} />
      <BestWeekdays overview={overview} />
      <RecurringTopics overview={overview} />
      <PastBroadcasts overview={overview} />
    </div>
  )
}
