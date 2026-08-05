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
    <section className="mb-6 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <h3 className="mb-3 font-semibold">{t('settings.title')}</h3>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="block text-sm text-zinc-400" htmlFor="stream-language">
            {t('settings.streamLanguage')}
          </label>
          <select
            id="stream-language"
            className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2"
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
          <label className="block text-sm text-zinc-400" htmlFor="screen-language">
            {t('settings.screenLanguage')}
          </label>
          <select
            id="screen-language"
            className="mt-1 w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2"
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
          className="rounded bg-violet-600 px-4 py-2 text-sm font-medium disabled:opacity-50"
          onClick={save}
          disabled={state === 'saving'}
        >
          {t('settings.save')}
        </button>
        {state === 'saved' && (
          <span className="text-sm text-zinc-400">{t('settings.saved')}</span>
        )}
        {state === 'failed' && (
          <span role="alert" className="text-sm text-red-400">
            {t('settings.failed')}
          </span>
        )}
      </div>
      <p className="mt-2 text-xs text-zinc-500">{t('settings.timezone', { zone: me.timezone })}</p>
    </section>
  )
}
