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
import { fmtInt, fmtMoney, t, type MessageKey } from '../i18n'
import { liveCount } from './StreamsList'
import type { ChannelOverview, GoalOut, GrowthPoint } from '../types'

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
      <h3 className="mb-1 text-lg font-bold">{t('channel.loyal')}</h3>
      <p className="mb-3 text-sm text-zinc-500">{t('channel.loyalSub')}</p>
      <div className="space-y-2">
        {overview.loyal_chatters.map((chatter, index) => (
          <div
            key={chatter.author_login}
            className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900 p-3"
          >
            <span className="w-6 shrink-0 text-sm font-bold tabular-nums text-zinc-600">
              {index + 1}.
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
              {liveCount(chatter.streams_attended)} ·{' '}
              {t('chatters.msgs', { n: fmtInt(chatter.total_messages) })} ·{' '}
              {t('channel.loyalLastSeen', { date: formatDate(chatter.last_seen) })}
            </span>
            {chatter.followed && (
              <span className="rounded-full border border-emerald-800 px-2 py-0.5 text-[10px] text-emerald-400">
                {t('channel.follower')}
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
      <h3 className="mb-1 text-lg font-bold">{t('channel.bestWeekdays')}</h3>
      <p className="mb-3 text-sm text-zinc-500">{t('channel.bestWeekdaysSub')}</p>
      <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        {overview.best_weekdays.map((slot) => (
          <div key={slot.weekday} className="flex items-center gap-3">
            <span className="w-20 shrink-0 text-sm capitalize text-zinc-300">
              {t(`weekday.${slot.weekday}` as MessageKey)}
            </span>
            <div className="h-4 flex-1 overflow-hidden rounded bg-zinc-800">
              <div
                className="h-full rounded bg-sky-500"
                style={{ width: `${(slot.avg_peak_viewers / max) * 100}%` }}
              />
            </div>
            <span className="w-28 shrink-0 text-right text-xs tabular-nums text-zinc-400">
              {slot.avg_peak_viewers} · {liveCount(slot.streams)}
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
            label: t('channel.growth.peak'),
            data: growth.map((point) => point.peak_viewers),
            borderColor: '#38bdf8',
            backgroundColor: 'rgba(56, 189, 248, 0.1)',
            fill: 'origin',
            tension: 0.3,
            yAxisID: 'y',
          },
          {
            label: t('channel.growth.newFollowers'),
            data: growth.map((point) => point.followers_gained),
            borderColor: '#34d399',
            tension: 0.3,
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
            title: { display: true, text: t('chart.axis.viewers'), color: '#71717a' },
            ticks: { color: '#71717a' },
            grid: { color: '#27272a' },
          },
          y1: {
            position: 'right',
            title: { display: true, text: t('channel.growth.axisFollowers'), color: '#71717a' },
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
      <h3 className="mb-3 text-lg font-bold">{t('channel.growth')}</h3>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        <div className="h-72 w-full">
          <canvas ref={canvasRef} />
        </div>
      </div>
    </div>
  )
}

function RecurringTopics({ overview }: { overview: ChannelOverview }) {
  const recurring = overview.recurring_topics.filter((topic) => topic.streams > 1)
  if (recurring.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">{t('channel.recurring')}</h3>
      <p className="mb-3 text-sm text-zinc-500">{t('channel.recurringSub')}</p>
      <div className="flex flex-wrap gap-2">
        {recurring.map((topic) => (
          <span
            key={topic.name}
            className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-sm"
          >
            {topic.name}{' '}
            <span className="text-zinc-500">{t('channel.recurringCount', { n: topic.streams })}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function ContentRevenue({ overview }: { overview: ChannelOverview }) {
  const buckets = overview.content_revenue
  if (buckets.length === 0) return null
  const maxPerHour = Math.max(...buckets.map((bucket) => bucket.usd_per_hour), 0.01)
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">{t('content.title')}</h3>
      <p className="mb-3 text-sm text-zinc-500">{t('content.subtitle')}</p>
      <div className="space-y-2 text-sm">
        {buckets.map((bucket) => (
          <div key={bucket.category} className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
            <div className="mb-1 flex items-center justify-between">
              <span className="font-semibold">{bucket.category}</span>
              <span className="text-emerald-400">
                {fmtMoney(bucket.usd_per_hour)}
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
                {t('content.streamsAndPeak', {
                  streams: liveCount(bucket.streams),
                  peak: fmtInt(bucket.avg_peak_viewers),
                })}
              </span>
              <span>{t('content.total', { value: fmtMoney(bucket.estimated_usd) })}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function RecommendationsSection({ overview }: { overview: ChannelOverview }) {
  const recs = overview.recommendations
  if (recs.length === 0) return null
  return (
    <div className="mb-6 rounded-lg border border-purple-900/60 bg-purple-950/20 p-4">
      <h3 className="mb-1 text-lg font-bold">{t('reco.title')}</h3>
      <p className="mb-3 text-xs text-zinc-500">{t('reco.subtitle')}</p>
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
      <h3 className="mb-3 text-lg font-bold">{t('subs.title')}</h3>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            {t('subs.active')}
          </p>
          <p className="text-2xl font-bold text-purple-300">{fmtInt(total)}</p>
          <div className="mt-2 space-y-1 text-sm">
            {tiers.map((tier) => (
              <div key={tier.tier} className="flex justify-between text-zinc-400">
                <span>{TIER_LABELS[tier.tier] ?? tier.tier}</span>
                <span>{tier.count}</span>
              </div>
            ))}
            <div className="flex justify-between text-zinc-500">
              <span>{t('subs.gifted')}</span>
              <span>{gifted_pct}%</span>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            {t('subs.churn')}
          </p>
          <p className="text-2xl font-bold text-red-400">{subs_ended}</p>
          <p className="text-xs text-zinc-500">{t('subs.churnAllNote')}</p>
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            {t('subs.topBits')}
          </p>
          {top_bits.length > 0 ? (
            <div className="space-y-1 text-sm">
              {top_bits.slice(0, 5).map((leader, index) => (
                <div key={leader.login} className="flex justify-between">
                  <span>
                    <span className="mr-2 text-zinc-600">{index + 1}.</span>
                    <span className="text-purple-300">{leader.login}</span>
                  </span>
                  <span className="text-zinc-400">{fmtInt(leader.score)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-zinc-600">{t('subs.noLeaderboard')}</p>
          )}
        </div>
      </div>
    </div>
  )
}

// Twitch's five goal types. `sinceCreated` marks the ones whose current_amount
// counts only what was gained after the goal was created (so a per-day pace is
// meaningful); the totals include pre-goal history, where a pace would mislead.
const GOALS_SINCE_CREATED = new Set(['new_subscription', 'new_subscription_count'])

const MS_PER_DAY = 86_400_000

function daysSince(iso: string): number {
  return (Date.now() - new Date(iso).getTime()) / MS_PER_DAY
}

function ageLabel(iso: string): string {
  const days = Math.floor(daysSince(iso))
  if (days < 1) return t('goal.createdToday')
  return t(days > 1 ? 'goal.activeDaysPlural' : 'goal.activeDays', { n: days })
}

function paceLabel(goal: GoalOut): string | null {
  if (!GOALS_SINCE_CREATED.has(goal.goal_type) || goal.created_at === null) return null
  if (goal.current_amount >= goal.target_amount) return null
  const days = daysSince(goal.created_at)
  if (days < 1) return null
  const perDay = goal.current_amount / days
  if (perDay <= 0) return t('goal.noProgress')
  const eta = Math.ceil((goal.target_amount - goal.current_amount) / perDay)
  return t(eta > 1 ? 'goal.pacePlural' : 'goal.pace', { perDay: perDay.toFixed(1), eta })
}

function GoalItem({ goal }: { goal: GoalOut }) {
  const label = goal.description ?? t(`goal.${goal.goal_type}.label` as MessageKey)
  const unit = t(`goal.${goal.goal_type}.unit` as MessageKey)
  const hint = t(`goal.${goal.goal_type}.hint` as MessageKey)
  const reached = goal.current_amount >= goal.target_amount
  const remaining = Math.max(goal.target_amount - goal.current_amount, 0)
  const pace = paceLabel(goal)
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-zinc-400">
          {fmtInt(goal.current_amount)}/{fmtInt(goal.target_amount)}
          <span className="ml-1 text-zinc-600">{unit}</span>
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded bg-zinc-800">
        <div
          className={`h-full rounded ${reached ? 'bg-emerald-500' : 'bg-purple-500'}`}
          style={{ width: `${Math.min(goal.pct, 100)}%` }}
        />
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-zinc-500">
        <span>{goal.pct}%</span>
        {reached ? (
          <span className="text-emerald-400">{t('goal.reachedFull')}</span>
        ) : (
          <span>{t('goal.remaining', { n: fmtInt(remaining), unit })}</span>
        )}
        {goal.created_at && <span>· {ageLabel(goal.created_at)}</span>}
        {pace && <span>· {pace}</span>}
      </div>
      <p className="mt-0.5 text-[11px] text-zinc-600">{hint}</p>
    </div>
  )
}

function CommunityHealth({ overview }: { overview: ChannelOverview }) {
  const { engaged_viewer_pct, vips, goals } = overview.community
  if (engaged_viewer_pct === null && vips.length === 0 && goals.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">{t('community.title')}</h3>
      <div className="grid gap-4 md:grid-cols-3">
        {goals.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 md:col-span-2">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              {t('goals.title')}
            </p>
            <div className="space-y-4 text-sm">
              {goals.map((goal) => (
                <GoalItem key={goal.goal_type + goal.description} goal={goal} />
              ))}
            </div>
          </div>
        )}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            {t('followers.chatEngagement')}
          </p>
          {engaged_viewer_pct !== null ? (
            <>
              <p className="text-2xl font-bold text-emerald-400">{engaged_viewer_pct}%</p>
              <p className="text-xs text-zinc-500">{t('channel.engagedPct')}</p>
            </>
          ) : (
            <p className="text-sm text-zinc-600">{t('channel.noViewerData')}</p>
          )}
        </div>
      </div>
      {vips.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            {t('channel.vips')}
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
  const maxRedemptions = Math.max(...top_rewards.map((reward) => reward.redemptions), 1)
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">{t('engagement.title')}</h3>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            {t('engagement.hypeTrains')}
          </p>
          {hype_train.count > 0 ? (
            <div className="space-y-1 text-sm">
              <p className="text-2xl font-bold text-purple-300">{hype_train.count}</p>
              <p className="text-zinc-400">
                {t('engagement.bestLevel', { n: hype_train.best_level })}
              </p>
              <p className="text-zinc-500">
                {t('engagement.contributed', { n: fmtInt(hype_train.total_contributed) })}
              </p>
            </div>
          ) : (
            <p className="text-sm text-zinc-600">{t('engagement.noHypeTrainEver')}</p>
          )}
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            {t('engagement.topRewards')}
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
                  <span className="w-8 shrink-0 text-right text-zinc-400">{reward.redemptions}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-zinc-600">{t('engagement.noRewardsEver')}</p>
          )}
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            {t('engagement.ads')}
          </p>
          {ads.breaks > 0 ? (
            <div className="space-y-1 text-sm">
              <p className="text-zinc-400">
                {t(ads.breaks > 1 ? 'engagement.adBreaksPlural' : 'engagement.adBreaks', {
                  n: ads.breaks,
                  minutes: Math.round(ads.total_seconds / 60),
                })}
              </p>
              {ads.avg_viewer_change_pct !== null && (
                <p className={ads.avg_viewer_change_pct < 0 ? 'text-red-400' : 'text-emerald-400'}>
                  {t('engagement.adViewers', {
                    pct:
                      (ads.avg_viewer_change_pct > 0 ? '+' : '') + String(ads.avg_viewer_change_pct),
                  })}
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-zinc-600">{t('engagement.noAdsEver')}</p>
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
      <h3 className="mb-1 text-lg font-bold">{t('channel.pastBroadcasts')}</h3>
      <p className="mb-3 text-sm text-zinc-500">{t('channel.pastBroadcastsSub')}</p>
      <div className="space-y-2">
        {overview.past_broadcasts.map((vod) => (
          <a
            key={vod.url}
            href={vod.url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-900 p-3 text-sm hover:border-zinc-600"
          >
            <span className="min-w-0 flex-1 truncate">{vod.title ?? t('channel.noTitle')}</span>
            <span className="shrink-0 text-zinc-500">{formatDate(vod.published_at)}</span>
            <span className="shrink-0 text-zinc-500">{formatDuration(vod.duration_seconds)}</span>
            <span className="w-20 shrink-0 text-right text-zinc-400">
              {t('channel.views', { n: fmtInt(vod.view_count) })}
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
        <h3 className="mb-1 text-lg font-bold">{t('channel.monetization')}</h3>
        <p className="text-sm text-zinc-500">{t('channel.noMonetization')}</p>
      </div>
    )
  }
  const maxTopic = Math.max(...finance.top_monetizing_topics.map((topic) => topic.estimated_usd), 0.01)
  const maxRevenue = Math.max(...overview.growth.map((point) => point.estimated_usd), 0.01)
  const paidStreams = overview.growth.filter((point) => point.estimated_usd > 0)

  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">{t('channel.monetizationAll')}</h3>
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-emerald-900/60 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">{t('money.estimated')}</p>
          <p className="text-xl font-bold text-emerald-400">
            {fmtMoney(finance.total_estimated_usd)}
          </p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">{t('money.bits')}</p>
          <p className="text-xl font-bold">{fmtInt(finance.total_bits)}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">{t('money.subs')}</p>
          <p className="text-xl font-bold">{fmtInt(finance.total_subs)}</p>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
          <p className="text-xs text-zinc-500">{t('money.gifts')}</p>
          <p className="text-xl font-bold">{fmtInt(finance.total_gifts)}</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {finance.top_contributors.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              {t('contributors.title')}
            </p>
            <div className="space-y-1.5 text-sm">
              {finance.top_contributors.map((contributor, index) => (
                <div key={contributor.login} className="flex items-center justify-between">
                  <span>
                    <span className="mr-2 text-zinc-600">{index + 1}.</span>
                    <span className="text-purple-300">{contributor.login}</span>
                    <span className="ml-2 text-xs text-zinc-500">
                      {t(contributor.streams > 1 ? 'finance.inStreamsPlural' : 'finance.inStreams', {
                        n: contributor.streams,
                      })}
                    </span>
                  </span>
                  <span className="font-semibold text-emerald-400">
                    {fmtMoney(contributor.estimated_usd)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {finance.top_monetizing_topics.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              {t('channel.topMonetizingTopics')}
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
                  <span className="w-16 shrink-0 text-right text-emerald-400">
                    {fmtMoney(topic.estimated_usd)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {paidStreams.length > 0 && (
        <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            {t('channel.revenuePerStream')}
          </p>
          <div className="space-y-2 text-sm">
            {paidStreams.map((point) => (
              <a
                key={point.stream_id}
                href={`#/stream/${point.stream_id}`}
                className="flex items-center gap-3 hover:text-purple-300"
              >
                <span className="w-48 shrink-0 truncate">
                  {point.title ?? t('live.number', { id: point.stream_id })}
                </span>
                <div className="h-2 flex-1 overflow-hidden rounded bg-zinc-800">
                  <div
                    className="h-full rounded bg-emerald-500"
                    style={{ width: `${(point.estimated_usd / maxRevenue) * 100}%` }}
                  />
                </div>
                <span className="w-16 shrink-0 text-right text-emerald-400">
                  {fmtMoney(point.estimated_usd)}
                </span>
              </a>
            ))}
          </div>
        </div>
      )}
      <p className="mt-2 text-[11px] text-zinc-600">{t('money.disclaimer')}</p>
    </div>
  )
}

function AccountSummary({ overview }: { overview: ChannelOverview }) {
  return (
    <div className="mb-6 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-bold">{t('channel.accountSummary')}</h3>
        <span className="text-xs text-zinc-500">
          {t('channel.connectedAt', { date: formatDate(overview.connected_at) })}
        </span>
      </div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        {t('channel.scopesTitle')}
      </p>
      <div className="flex flex-wrap gap-2">
        {overview.scopes.map((scope) => (
          <span
            key={scope}
            className="rounded-full border border-zinc-700 px-3 py-1 text-xs text-zinc-300"
          >
            {t(`scope.${scope}` as MessageKey)}
          </span>
        ))}
      </div>
    </div>
  )
}

export default function ChannelView() {
  const [overview, setOverview] = useState<ChannelOverview | null>(null)

  useEffect(() => {
    apiGet<ChannelOverview>('/api/channel').then(setOverview)
  }, [])

  if (overview === null) return <p className="text-zinc-400">{t('channel.loading')}</p>

  const noStreams = overview.total_streams === 0

  return (
    <div>
      <a href="#/" className="text-sm text-zinc-400 hover:text-zinc-200">
        {t('nav.back')}
      </a>
      <h2 className="mb-4 mt-2 text-xl font-bold">{t('channel.title')}</h2>
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatCard label={t('channel.stat.streams')} value={fmtInt(overview.total_streams)} />
        <StatCard label={t('channel.stat.messages')} value={fmtInt(overview.total_messages)} />
        <StatCard
          label={t('channel.stat.uniqueChatters')}
          value={fmtInt(overview.unique_chatters)}
        />
        <StatCard
          label={t('followers.kpi.total')}
          value={fmtInt(overview.total_followers_gained)}
        />
        <StatCard
          label={t('money.estimated')}
          value={fmtMoney(overview.finance.total_estimated_usd)}
        />
      </div>
      <AccountSummary overview={overview} />
      {noStreams && (
        <p className="mb-6 rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-400">
          {t('channel.noStreams')}
        </p>
      )}
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
