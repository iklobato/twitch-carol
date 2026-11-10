import { useState } from 'react'

import { apiPatch } from '../api'
import { t } from '../i18n'
import type { Me } from '../types'

/** Opt in/out of the weekly/monthly recap email. The address itself comes
 * from the Twitch login grant, not from a field here. */
export default function DigestSettings({ me }: { me: Me }) {
  const [weekly, setWeekly] = useState(me.digest_weekly)
  const [monthly, setMonthly] = useState(me.digest_monthly)
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'failed'>('idle')

  async function save(next: { digest_weekly?: boolean; digest_monthly?: boolean }) {
    setState('saving')
    try {
      await apiPatch('/api/channel/preferences', next)
      setState('saved')
    } catch {
      setState('failed')
    }
  }

  return (
    <section className="rounded-2xl border border-line bg-panel p-5">
      <h3 className="mb-2 font-display text-lg font-semibold">{t('digest.title')}</h3>
      <div className="flex flex-col gap-2">
        <label className="flex min-h-11 items-center gap-3 text-sm">
          <input
            type="checkbox"
            className="h-5 w-5 accent-accent"
            checked={weekly}
            onChange={(event) => {
              setWeekly(event.target.checked)
              save({ digest_weekly: event.target.checked })
            }}
          />
          {t('digest.weekly')}
        </label>
        <label className="flex min-h-11 items-center gap-3 text-sm">
          <input
            type="checkbox"
            className="h-5 w-5 accent-accent"
            checked={monthly}
            onChange={(event) => {
              setMonthly(event.target.checked)
              save({ digest_monthly: event.target.checked })
            }}
          />
          {t('digest.monthly')}
        </label>
      </div>
      {state === 'saved' && (
        <p className="mt-2 text-sm text-ink-muted">{t('digest.saved')}</p>
      )}
      {state === 'failed' && (
        <p role="alert" className="mt-2 text-sm text-red-400">
          {t('settings.failed')}
        </p>
      )}
      {!me.email && (
        <p className="mt-2 text-sm text-ink-muted">{t('digest.noEmail')}</p>
      )}
    </section>
  )
}
