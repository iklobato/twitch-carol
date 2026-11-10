import { useState } from 'react'

import { apiPatch } from '../api'
import { t } from '../i18n'
import type { Me } from '../types'

const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'pt', label: 'Português' },
] as const

/** The onboarding gate asks once. This is the way back for someone who picked
 * wrong, or who changed what they stream in: without it the only fix is a
 * database update. */
export default function LanguageSettings({ me }: { me: Me }) {
  const [streamLanguage, setStreamLanguage] = useState(me.stream_language ?? 'en')
  const [screenLanguage, setScreenLanguage] = useState(me.language)
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'failed'>('idle')

  async function save() {
    setState('saving')
    try {
      await apiPatch('/api/channel/preferences', {
        stream_language: streamLanguage,
        screen_language: screenLanguage,
      })
      // The screen language is read once at boot, so the new one only takes
      // effect on reload. Saying so beats a half-translated page.
      setState('saved')
    } catch {
      setState('failed')
    }
  }

  return (
    <section className="rounded-2xl border border-line bg-panel p-5">
      <h3 className="mb-4 font-display text-lg font-semibold">{t('settings.title')}</h3>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="block text-sm font-semibold" htmlFor="stream-language">
            {t('settings.streamLanguage')}
          </label>
          <select
            id="stream-language"
            className="mt-1.5 min-h-11 w-full rounded-lg border border-line-strong bg-panel-raised px-3"
            value={streamLanguage}
            onChange={(event) => setStreamLanguage(event.target.value)}
          >
            {LANGUAGES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-semibold" htmlFor="screen-language">
            {t('settings.screenLanguage')}
          </label>
          <select
            id="screen-language"
            className="mt-1.5 min-h-11 w-full rounded-lg border border-line-strong bg-panel-raised px-3"
            value={screenLanguage}
            onChange={(event) => setScreenLanguage(event.target.value)}
          >
            {LANGUAGES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          className="min-h-11 rounded-lg bg-accent px-4 text-sm font-semibold text-[#16112a] disabled:opacity-50"
          onClick={save}
          disabled={state === 'saving'}
        >
          {t('settings.save')}
        </button>
        {state === 'saved' && (
          <span className="text-sm text-ink-muted">{t('settings.saved')}</span>
        )}
        {state === 'failed' && (
          <span role="alert" className="text-sm text-red-400">
            {t('settings.failed')}
          </span>
        )}
      </div>
      <p className="mt-3 text-sm text-ink-muted">{t('settings.timezone', { zone: me.timezone })}</p>
    </section>
  )
}
