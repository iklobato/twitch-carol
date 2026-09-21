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
    <section className="mb-6 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <h3 className="mb-3 font-semibold">{t('digest.title')}</h3>
      <div className="flex flex-col gap-2">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={weekly}
            onChange={(event) => {
              setWeekly(event.target.checked)
              save({ digest_weekly: event.target.checked })
            }}
          />
          {t('digest.weekly')}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
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
        <p className="mt-2 text-sm text-zinc-400">{t('digest.saved')}</p>
      )}
      {state === 'failed' && (
        <p role="alert" className="mt-2 text-sm text-red-400">
          {t('settings.failed')}
        </p>
      )}
      {!me.email && (
        <p className="mt-2 text-xs text-zinc-500">{t('digest.noEmail')}</p>
      )}
    </section>
  )
}
