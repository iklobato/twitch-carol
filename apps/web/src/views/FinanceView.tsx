import { useEffect, useState } from 'react'
import { apiGet, formatDate } from '../api'
import { fmtInt, fmtMoney, t, type MessageKey } from '../i18n'
import PeriodPicker from '../components/PeriodPicker'
import { liveCount } from './StreamsList'
import type { FinanceOverview, FinancePeriod } from '../types'

function periodPhrase(period: FinancePeriod): string {
  return t(`finance.period.${period}` as MessageKey)
}

function Delta({ pct }: { pct: number | null }) {
  if (pct === null) return null
  const up = pct >= 0
  return (
    <span className={`text-sm font-semibold ${up ? 'text-emerald-400' : 'text-red-400'}`}>
      {up ? '▲' : '▼'} {Math.abs(pct)}%
      <span className="ml-1 text-xs font-normal text-zinc-500">{t('delta.vsPrevious')}</span>
    </span>
  )
}

function KpiRow({ finance }: { finance: FinanceOverview }) {
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
      <div className="rounded-lg border border-emerald-900/60 bg-zinc-900 p-3">
        <p className="text-xs text-zinc-500">{t('money.estimated')}</p>
        <p className="text-xl font-bold text-emerald-400">{fmtMoney(finance.estimated_usd)}</p>
        <Delta pct={finance.delta_pct} />
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
  )
}

function RevenueByStream({ finance }: { finance: FinanceOverview }) {
  if (finance.by_stream.length === 0) return null
  const max = Math.max(...finance.by_stream.map((row) => row.estimated_usd), 0.01)
  return (
    <div>
      <h3 className="mb-3 text-lg font-bold">{t('finance.revenueByStream')}</h3>
      <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm">
        {finance.by_stream.map((row) => (
          <a
            key={row.stream_id}
            href={`#/stream/${row.stream_id}`}
            className="flex items-center gap-3 hover:text-purple-300"
          >
            <span className="w-24 shrink-0 text-xs text-zinc-500">
              {formatDate(row.started_at)}
            </span>
            <span className="min-w-0 flex-1 truncate">
              {row.title ?? t('live.number', { id: row.stream_id })}
            </span>
            <div className="hidden h-2 w-40 overflow-hidden rounded bg-zinc-800 md:block">
              <div
                className="h-full rounded bg-emerald-500"
                style={{ width: `${(row.estimated_usd / max) * 100}%` }}
              />
            </div>
            <span className="w-16 shrink-0 text-right text-emerald-400">
              {fmtMoney(row.estimated_usd)}
            </span>
          </a>
        ))}
      </div>
    </div>
  )
}

function TopContributors({ finance }: { finance: FinanceOverview }) {
  if (finance.top_contributors.length === 0) return null
  return (
    <div>
      <h3 className="mb-3 text-lg font-bold">{t('contributors.title')}</h3>
      <div className="space-y-1.5 rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm">
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
  )
}

function ContentRevenue({ finance }: { finance: FinanceOverview }) {
  if (finance.by_content.length === 0) return null
  const maxPerHour = Math.max(...finance.by_content.map((b) => b.usd_per_hour), 0.01)
  return (
    <div className="mb-6">
      <h3 className="mb-1 text-lg font-bold">{t('content.title')}</h3>
      <p className="mb-3 text-sm text-zinc-500">{t('content.subtitle')}</p>
      <div className="space-y-2 text-sm">
        {finance.by_content.map((bucket) => (
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

function Engagement({ finance }: { finance: FinanceOverview }) {
  const { hype_train, top_rewards, ads } = finance.engagement
  if (hype_train.count === 0 && top_rewards.length === 0 && ads.breaks === 0) return null
  const maxRedemptions = Math.max(...top_rewards.map((r) => r.redemptions), 1)
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
            <p className="text-sm text-zinc-600">{t('engagement.noHypeTrainPeriod')}</p>
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
            <p className="text-sm text-zinc-600">{t('engagement.noRewardsPeriod')}</p>
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
              <p className="text-[11px] text-zinc-600">{t('engagement.adNote')}</p>
            </div>
          ) : (
            <p className="text-sm text-zinc-600">{t('engagement.noAdsPeriod')}</p>
          )}
        </div>
      </div>
    </div>
  )
}

const TIER_LABELS: Record<string, string> = {
  '1000': 'Tier 1',
  '2000': 'Tier 2',
  '3000': 'Tier 3',
}

function Subscribers({ finance }: { finance: FinanceOverview }) {
  const { total, tiers, gifted_pct, subs_ended, top_bits } = finance.subscribers
  if (total === 0 && top_bits.length === 0 && subs_ended === 0) return null
  return (
    <div className="mb-6">
      <div className="mb-3 flex items-baseline gap-2">
        <h3 className="text-lg font-bold">{t('subs.title')}</h3>
        <span className="rounded-full border border-zinc-700 px-2 py-0.5 text-[10px] text-zinc-400">
          {t('subs.currentState')}
        </span>
      </div>
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
          <p className="text-xs text-zinc-500">{t('subs.churnPeriodNote')}</p>
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

function Goals({ finance }: { finance: FinanceOverview }) {
  if (finance.goals.length === 0) return null
  return (
    <div className="mb-6">
      <div className="mb-3 flex items-baseline gap-2">
        <h3 className="text-lg font-bold">{t('goals.title')}</h3>
        <span className="rounded-full border border-zinc-700 px-2 py-0.5 text-[10px] text-zinc-400">
          {t('subs.currentState')}
        </span>
      </div>
      <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm">
        {finance.goals.map((goal) => {
          const reached = goal.current_amount >= goal.target_amount
          return (
            <div key={goal.goal_type + goal.description}>
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="font-medium">
                  {goal.description ?? t(`goal.${goal.goal_type}.label` as MessageKey)}
                </span>
                <span className="tabular-nums text-zinc-400">
                  {fmtInt(goal.current_amount)}/{fmtInt(goal.target_amount)}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded bg-zinc-800">
                <div
                  className={`h-full rounded ${reached ? 'bg-emerald-500' : 'bg-purple-500'}`}
                  style={{ width: `${Math.min(goal.pct, 100)}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                {goal.pct}%
                {reached && <span className="ml-2 text-emerald-400">{t('goals.reached')}</span>}
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Recommendations({ finance }: { finance: FinanceOverview }) {
  if (finance.recommendations.length === 0) return null
  return (
    <div className="mb-6 rounded-lg border border-purple-900/60 bg-purple-950/20 p-4">
      <h3 className="mb-1 text-lg font-bold">{t('reco.title')}</h3>
      <p className="mb-3 text-xs text-zinc-500">{t('reco.subtitle')}</p>
      <div className="space-y-3">
        {finance.recommendations.map((rec, index) => (
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

export default function FinanceView() {
  const [period, setPeriod] = useState<FinancePeriod>('30d')
  const [finance, setFinance] = useState<FinanceOverview | null>(null)

  useEffect(() => {
    setFinance(null)
    apiGet<FinanceOverview>(`/api/finance?period=${period}`)
      .then(setFinance)
      .catch(() => setFinance(null))
  }, [period])

  const nothingYet =
    finance !== null &&
    finance.money_events === 0 &&
    finance.engagement.hype_train.count === 0 &&
    finance.engagement.ads.breaks === 0 &&
    finance.subscribers.total === 0 &&
    finance.goals.length === 0

  return (
    <div>
      <a href="#/" className="text-sm text-zinc-400 hover:text-zinc-200">
        {t('nav.back')}
      </a>
      <div className="mb-4 mt-2 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-bold">{t('finance.title')}</h2>
        <PeriodPicker value={period} onChange={setPeriod} />
      </div>

      {finance === null ? (
        <p className="text-zinc-400">{t('finance.loading')}</p>
      ) : nothingYet ? (
        <p className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-400">
          {t('finance.nothing', { period: periodPhrase(period) })}
        </p>
      ) : (
        <>
          <p className="mb-4 text-sm text-zinc-500">
            {t('finance.intro', { period: periodPhrase(period) })}
          </p>
          <KpiRow finance={finance} />
          <div className="mb-6 grid items-start gap-4 md:grid-cols-2">
            <RevenueByStream finance={finance} />
            <TopContributors finance={finance} />
          </div>
          <ContentRevenue finance={finance} />
          <Engagement finance={finance} />
          <Subscribers finance={finance} />
          <Goals finance={finance} />
          <Recommendations finance={finance} />
        </>
      )}
    </div>
  )
}
