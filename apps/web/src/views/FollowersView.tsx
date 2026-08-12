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
import { fmtInt, fmtMoney, t, type MessageKey } from '../i18n'
import { liveCount } from './StreamsList'
import type {
  CohortRow,
  CollabCandidate,
  FollowerAi,
  FollowerKpis,
  FollowerProfile,
  FollowersOverview,
  FollowerSignals,
  FunnelStage,
  GrowthBucket,
  SegmentMember,
  TopFollower,
  Unfollow,
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

// Recent-window caps for the two time-series views (labeled when they truncate).
const VELOCITY_RECENT_DAYS = 60
const COHORT_RECENT_MONTHS = 12

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
      : t('followers.years', { n: (kpis.avg_account_age_days / 365).toFixed(1) })
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
      <StatCard
        label={t('followers.kpi.total')}
        value={fmtInt(kpis.total)}
        hint={
          kpis.stored === kpis.total
            ? undefined
            : t('followers.kpi.totalHint', { stored: fmtInt(kpis.stored) })
        }
      />
      <StatCard
        label={t('followers.kpi.streamers')}
        value={fmtInt(kpis.streamers)}
        hint={t('followers.kpi.streamersHint', {
          affiliates: kpis.affiliates,
          partners: kpis.partners,
        })}
      />
      <StatCard label={t('followers.kpi.new7d')} value={fmtInt(kpis.new_7d)} />
      <StatCard label={t('followers.kpi.new30d')} value={fmtInt(kpis.new_30d)} />
      <StatCard label={t('followers.kpi.avgAge')} value={age} />
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
            label: t('followers.growth.cumulative'),
            data: growth.map((point) => point.cumulative),
            borderColor: '#a855f7',
            backgroundColor: 'rgba(168, 85, 247, 0.12)',
            fill: 'origin',
            tension: 0.3,
            yAxisID: 'y',
          },
          {
            type: 'bar',
            label: t('followers.growth.new'),
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
            title: { display: true, text: t('followers.growth.axisCumulative'), color: '#71717a' },
            ticks: { color: '#71717a' },
            grid: { color: '#27272a' },
          },
          y1: {
            position: 'right',
            title: { display: true, text: t('followers.growth.axisNew'), color: '#71717a' },
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
      <h3 className="mb-3 text-lg font-bold">{t('followers.growth')}</h3>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        <div className="h-72 w-full">
          <canvas ref={canvasRef} />
        </div>
      </div>
    </div>
  )
}

function ProfileCard({ profile }: { profile: FollowerProfile }) {
  const badge = profile.broadcaster_type
    ? t(`type.${profile.broadcaster_type}` as MessageKey)
    : null
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
          {t('followers.followedOn', { date: formatDate(profile.followed_at) })}
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

function UnfollowGrid({ unfollows }: { unfollows: Unfollow[] }) {
  if (unfollows.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">{t('followers.unfollows.title')}</h3>
      <p className="mb-3 text-sm text-zinc-500">{t('followers.unfollows.subtitle')}</p>
      <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        {unfollows.map((person) => (
          <div
            key={`${person.login}-${person.detected_at}`}
            className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900 p-3"
          >
            {person.profile_image_url ? (
              <img
                src={person.profile_image_url}
                alt={person.login}
                className="h-10 w-10 shrink-0 rounded-full opacity-60"
              />
            ) : (
              <div className="h-10 w-10 shrink-0 rounded-full bg-zinc-800" />
            )}
            <div className="min-w-0 flex-1">
              <a
                href={`https://twitch.tv/${person.login}`}
                target="_blank"
                rel="noreferrer"
                className="block truncate text-sm font-semibold text-zinc-300 hover:underline"
              >
                {person.display_name ?? person.login}
              </a>
              <p className="truncate text-xs text-zinc-500">
                {t('followers.unfollows.stayed', { n: person.days_followed })}
              </p>
            </div>
            <span className="shrink-0 text-[10px] text-zinc-600">
              {formatDate(person.detected_at)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// The charts below describe the followers we hold rows for, which trails Twitch's
// own count until the sync worker finishes a channel. Saying so beats a chart that
// looks complete and is not.
// "Followers" is Twitch's own count; every other number on this page is computed
// over the rows we hold. When the two disagree the row reads as broken ("42
// followers, 2,500 of them streamers"), so the gap has to be stated in whichever
// direction it goes: fewer rows than the count means a sync still in progress,
// more means rows Twitch no longer lists.
function SyncNotice({ kpis }: { kpis: FollowerKpis }) {
  if (kpis.stored === kpis.total) return null
  const key = kpis.stored < kpis.total ? 'followers.syncing' : 'followers.extraRows'
  return (
    <p className="mb-4 rounded-lg border border-amber-900 bg-amber-950/40 p-3 text-xs text-amber-300">
      {t(key, { stored: fmtInt(kpis.stored), total: fmtInt(kpis.total) })}
    </p>
  )
}

function Bars({
  rows,
  color,
  prefix,
}: {
  rows: { label: string; count: number }[]
  color: string
  prefix: 'followerType' | 'age'
}) {
  const max = Math.max(...rows.map((row) => row.count), 1)
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.label} className="flex items-center gap-3 text-sm">
          <span className="w-28 shrink-0 text-zinc-300">
            {t(`${prefix}.${row.label}` as MessageKey)}
          </span>
          <div className="h-3 flex-1 overflow-hidden rounded bg-zinc-800">
            <div
              className={`h-full rounded ${color}`}
              style={{ width: `${(row.count / max) * 100}%` }}
            />
          </div>
          <span className="w-12 shrink-0 text-right tabular-nums text-zinc-400">
            {fmtInt(row.count)}
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
      <h3 className="mb-3 text-lg font-bold">{t('followers.composition')}</h3>
      <div className="grid gap-4 md:grid-cols-2">
        {by_type.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              {t('followers.byType')}
            </p>
            <Bars rows={by_type} color="bg-sky-500" prefix="followerType" />
          </div>
        )}
        {by_age.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              {t('followers.byAge')}
            </p>
            <Bars rows={by_age} color="bg-purple-500" prefix="age" />
          </div>
        )}
      </div>
      <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
          {t('followers.chatEngagement')}
        </p>
        <p className="text-sm text-zinc-400">
          <span className="font-bold text-emerald-400">{chattyPct}%</span>{' '}
          {t('followers.chattyText', {
            chatty: fmtInt(chatty),
            engaged: fmtInt(engaged),
            silent: fmtInt(silent),
          })}
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
      <h3 className="mb-1 text-lg font-bold">{t('followers.recoTitle')}</h3>
      <p className="mb-3 text-xs text-zinc-500">{t('followers.recoSubtitle')}</p>
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

const STAGE_STYLE: Record<string, string> = {
  follower: 'border-zinc-700 text-zinc-400',
  engaged: 'border-sky-800 text-sky-300',
  subscriber: 'border-purple-800 text-purple-300',
  paying: 'border-emerald-800 text-emerald-300',
}

function StageBadge({ stage }: { stage: string }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[10px] ${STAGE_STYLE[stage] ?? 'border-zinc-700 text-zinc-400'}`}
    >
      {t(`stage.${stage}` as MessageKey)}
    </span>
  )
}

function Funnel({ funnel }: { funnel: FunnelStage[] }) {
  if (funnel.length === 0) return null
  const top = funnel[0].count || 1
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">{t('funnel.title')}</h3>
      <p className="mb-3 text-sm text-zinc-500">{t('funnel.subtitle')}</p>
      <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        {funnel.map((stage) => {
          const pct = Math.round((stage.count / top) * 100)
          return (
            <div key={stage.stage} className="flex items-center gap-3 text-sm">
              <span className="w-40 shrink-0 text-zinc-300">
                {t(`funnel.stage.${stage.stage}` as MessageKey)}
              </span>
              <div className="h-4 flex-1 overflow-hidden rounded bg-zinc-800">
                <div
                  className="h-full rounded bg-gradient-to-r from-sky-600 to-emerald-500"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="w-24 shrink-0 text-right tabular-nums text-zinc-400">
                {fmtInt(stage.count)} · {pct}%
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
  const recent = cohorts.slice(-COHORT_RECENT_MONTHS).reverse()
  const capped = cohorts.length > COHORT_RECENT_MONTHS
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">
        {t('cohorts.title')}
        {capped && t('cohorts.capped', { n: COHORT_RECENT_MONTHS })}
      </h3>
      <p className="mb-3 text-sm text-zinc-500">{t('cohorts.subtitle')}</p>
      <div className="overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-900">
        <table className="w-full min-w-[32rem] text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-left text-xs uppercase tracking-wide text-zinc-500">
              <th className="p-3">{t('cohorts.month')}</th>
              <th className="p-3 text-right">{t('cohorts.followers')}</th>
              <th className="p-3 text-right">{t('cohorts.chatted')}</th>
              <th className="p-3 text-right">{t('cohorts.subscribed')}</th>
              <th className="p-3 text-right">{t('cohorts.paid')}</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((row) => (
              <tr key={row.month} className="border-b border-zinc-800/50 last:border-0">
                <td className="p-3 text-zinc-300">{row.month}</td>
                <td className="p-3 text-right tabular-nums">{row.size}</td>
                <td className="p-3 text-right tabular-nums text-sky-300">
                  {row.chatted}{' '}
                  <span className="text-zinc-600">
                    ({Math.round((row.chatted / row.size) * 100)}%)
                  </span>
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
              {index + 1}.
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
                <span className="font-semibold text-emerald-400">{fmtMoney(row.estimated_usd)}</span>
              ) : (
                <span className="font-semibold text-purple-300">
                  {t(row.sub_months === 1 ? 'followers.month' : 'followers.months', {
                    n: row.sub_months,
                  })}
                </span>
              )}
            </span>
            <span className="w-full text-xs text-zinc-500 md:w-auto md:pl-2">
              {t('chatters.msgs', { n: fmtInt(row.messages) })} · {liveCount(row.streams_present)}
              {row.last_seen && t('followers.lastSeen', { date: formatDate(row.last_seen) })}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function VelocitySparkline({ velocity }: { velocity: VelocityDay[] }) {
  if (velocity.length === 0) return null
  const recent = velocity.slice(-VELOCITY_RECENT_DAYS)
  const max = Math.max(...recent.map((day) => day.follows), 1)
  const capped = velocity.length > VELOCITY_RECENT_DAYS
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">
        {t('signals.velocity')}
        {capped && t('signals.velocityCapped', { n: VELOCITY_RECENT_DAYS })}
        {t('signals.velocityNote')}
      </p>
      <div className="flex h-24 items-end gap-0.5">
        {recent.map((day) => (
          <div
            key={day.day}
            title={
              t('signals.velocityTooltip', { day: day.day, follows: day.follows }) +
              (day.is_spike ? t('signals.spikeSuffix') : '')
            }
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
    raids.length > 0 || suspicious.length > 0 || velocity.length > 0 || topic_follows.length > 0
  if (!hasAny) return null
  return (
    <div className="mb-6">
      <h3 className="mb-3 text-lg font-bold">{t('signals.title')}</h3>
      <div className="mb-3">
        <VelocitySparkline velocity={velocity} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {raids.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              {t('signals.raids')}
            </p>
            <div className="space-y-1.5 text-sm">
              {raids.slice(0, 6).map((raid, index) => (
                <div key={index} className="flex items-center justify-between">
                  <span className="text-purple-300">
                    {raid.raider_login ?? 'raid'}{' '}
                    <span className="text-zinc-600">
                      {t('signals.raidViewers', { n: raid.viewers })}
                    </span>
                  </span>
                  <span className="text-emerald-400">
                    {t('signals.raidFollows', { n: raid.follows_after })}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
        {topic_follows.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              {t('signals.topicFollows')}
            </p>
            <div className="space-y-1.5 text-sm">
              {topic_follows.slice(0, 6).map((topic, index) => (
                <div key={index} className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate">{topic.topic}</span>
                  <span className="shrink-0 text-emerald-400">+{topic.follows}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      {suspicious.length > 0 && (
        <div className="mt-4 rounded-lg border border-red-900/50 bg-red-950/20 p-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-red-400">
            {t('signals.suspicious', { n: suspicious_total })}
          </p>
          <p className="mb-3 text-xs text-zinc-500">{t('signals.suspiciousNote')}</p>
          <div className="flex flex-wrap gap-2">
            {suspicious.slice(0, 18).map((profile) => (
              <span
                key={profile.login}
                title={profile.reasons
                  .map((reason) => t(`suspicious.${reason}` as MessageKey))
                  .join(', ')}
                className="rounded-full border border-red-800 px-3 py-1 text-xs text-red-200"
              >
                {profile.display_name ?? profile.login}{' '}
                <span className="text-red-400">· {profile.score}</span>
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

const MEMBERS_PER_PAGE = 5

// `total` is the segment's real size, which is larger than the list whenever the
// segment has more members than the response carries.
function MemberList({ members, total }: { members: SegmentMember[]; total: number }) {
  const [page, setPage] = useState(0)
  const pages = Math.ceil(members.length / MEMBERS_PER_PAGE)
  const start = page * MEMBERS_PER_PAGE
  const slice = members.slice(start, start + MEMBERS_PER_PAGE)
  const listed = members.length
  return (
    <div className="mb-2">
      {total > listed && (
        <p className="mb-1 text-[11px] text-zinc-600">
          {t('members.sample', { listed: fmtInt(listed), total: fmtInt(total) })}
        </p>
      )}
      <ul className="mb-1 space-y-0.5 text-xs">
        {slice.map((member) => (
          <li key={member.login}>
            <a
              href={`https://twitch.tv/${member.login}`}
              target="_blank"
              rel="noreferrer"
              className="text-zinc-400 hover:text-purple-300 hover:underline"
            >
              {member.display_name ?? member.login}
            </a>
          </li>
        ))}
      </ul>
      {pages > 1 && (
        <div className="flex items-center gap-2 text-[11px] text-zinc-600">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="rounded border border-zinc-800 px-1.5 py-0.5 hover:text-zinc-300 disabled:opacity-30"
          >
            ‹
          </button>
          <span className="tabular-nums">
            {t('members.range', {
              from: start + 1,
              to: start + slice.length,
              total: fmtInt(members.length),
            })}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
            disabled={page >= pages - 1}
            className="rounded border border-zinc-800 px-1.5 py-0.5 hover:text-zinc-300 disabled:opacity-30"
          >
            ›
          </button>
        </div>
      )}
    </div>
  )
}

function AiSection({ ai }: { ai: FollowerAi }) {
  const { segments, audience_summary, reactivations } = ai
  if (segments.length === 0 && !audience_summary && reactivations.length === 0) return null
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">{t('ai.title')}</h3>
      <p className="mb-3 text-sm text-zinc-500">{t('ai.subtitle')}</p>

      {audience_summary && (
        <div className="mb-4 rounded-lg border border-purple-900/60 bg-purple-950/20 p-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-purple-300">
            {t('ai.whoFollows')}
          </p>
          <p className="text-sm">{audience_summary}</p>
        </div>
      )}

      {segments.length > 0 && (
        <div className="mb-4 grid gap-3 md:grid-cols-2">
          {segments.map((segment) => (
            <div
              key={segment.key}
              className={`rounded-lg border p-4 ${SEGMENT_COLOR[segment.key] ?? 'border-zinc-800 bg-zinc-900'}`}
            >
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="font-semibold">{segment.label}</span>
                <span className="tabular-nums text-zinc-400">{fmtInt(segment.count)}</span>
              </div>
              <p className="mb-2 text-xs text-zinc-500">{segment.description}</p>
              {segment.members.length > 0 && (
                <MemberList members={segment.members} total={segment.count} />
              )}
              {segment.action && (
                <p className="rounded bg-black/30 p-2 text-sm text-zinc-200">→ {segment.action}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {reactivations.length > 0 && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/10 p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-amber-400">
            {t('ai.reactivations')}
          </p>
          <div className="space-y-3">
            {reactivations.map((reactivation, index) => (
              <div key={index} className="text-sm">
                <span className="font-semibold text-purple-300">{reactivation.who}</span>
                <p className="mt-0.5 rounded bg-black/30 p-2 text-zinc-200">
                  {reactivation.message}
                </p>
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
  const shared = collab.filter((candidate) => candidate.shared_category).length
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">{t('collab.title')}</h3>
      <p className="mb-3 text-sm text-zinc-500">
        {t('collab.subtitle')}{' '}
        {shared > 0 && (
          <span className="text-emerald-400">{t('collab.shared', { n: shared })}</span>
        )}
      </p>
      <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        {collab.map((candidate) => (
          <div
            key={candidate.login}
            className={`flex items-center gap-3 rounded-lg border p-3 ${candidate.shared_category ? 'border-emerald-800 bg-emerald-950/20' : 'border-zinc-800 bg-zinc-900'}`}
          >
            {candidate.profile_image_url ? (
              <img
                src={candidate.profile_image_url}
                alt={candidate.login}
                className="h-10 w-10 shrink-0 rounded-full"
              />
            ) : (
              <div className="h-10 w-10 shrink-0 rounded-full bg-zinc-800" />
            )}
            <div className="min-w-0 flex-1">
              <a
                href={`https://twitch.tv/${candidate.login}`}
                target="_blank"
                rel="noreferrer"
                className="block truncate text-sm font-semibold text-purple-300 hover:underline"
              >
                {candidate.display_name ?? candidate.login}
              </a>
              <p className="truncate text-xs text-zinc-500">
                {candidate.stream_category ?? t('collab.unknownCategory')}
                {candidate.stream_language && ` · ${candidate.stream_language}`}
              </p>
            </div>
            {candidate.shared_category && (
              <span className="shrink-0 rounded-full border border-emerald-700 px-2 py-0.5 text-[10px] text-emerald-300">
                {t('collab.sameCategory')}
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

  if (overview === null) return <p className="text-zinc-400">{t('followers.loading')}</p>

  return (
    <div>
      <a href="#/" className="text-sm text-zinc-400 hover:text-zinc-200">
        {t('nav.back')}
      </a>
      <h2 className="mb-4 mt-2 text-xl font-bold">{t('followers.title')}</h2>
      {overview.kpis.total === 0 ? (
        <p className="text-zinc-400">{t('followers.empty')}</p>
      ) : (
        <>
          <Kpis overview={overview} />
          <SyncNotice kpis={overview.kpis} />
          <Recommendations overview={overview} />
          <AiSection ai={overview.ai} />
          <Funnel funnel={overview.funnel} />
          <GrowthChart growth={overview.growth} />
          <Signals signals={overview.signals} />
          <Composition overview={overview} />
          <FollowerTable
            title={t('followers.topValue')}
            subtitle={t('followers.topValueSub')}
            rows={overview.top_value}
            valueColumn="usd"
          />
          <FollowerTable
            title={t('followers.loyal')}
            subtitle={t('followers.loyalSub')}
            rows={overview.loyal_subscribers}
            valueColumn="months"
          />
          <Cohorts cohorts={overview.cohorts} />
          <CollabSection collab={overview.collab} />
          <ProfileGrid
            title={t('followers.recent')}
            subtitle={t('followers.recentSub')}
            profiles={overview.recent}
          />
          <UnfollowGrid unfollows={overview.unfollows} />
        </>
      )}
    </div>
  )
}
