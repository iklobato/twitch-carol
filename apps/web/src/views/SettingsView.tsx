import DigestSettings from '../components/DigestSettings'
import LanguageSettings from '../components/LanguageSettings'
import { t, type MessageKey } from '../i18n'
import type { Me } from '../types'

function DataAccess({ scopes }: { scopes: string[] }) {
  // A channel with no stored scopes would get an empty card.
  if (scopes.length === 0) return null
  return (
    <section className="rounded-2xl border border-line bg-panel p-5">
      <h3 className="font-display text-lg font-semibold">{t('channel.scopesTitle')}</h3>
      <div className="mt-4 flex flex-wrap gap-2">
        {scopes.map((scope) => (
          <span
            key={scope}
            className="rounded-full border border-line-strong bg-panel-raised px-3 py-1.5 text-sm text-ink-muted"
          >
            {t(`scope.${scope}` as MessageKey)}
          </span>
        ))}
      </div>
    </section>
  )
}

export default function SettingsView({ me }: { me: Me }) {
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <h1 className="font-display text-3xl font-semibold">{t('settings.pageTitle')}</h1>
      <LanguageSettings me={me} />
      <DigestSettings me={me} />
      <DataAccess scopes={me.scopes} />
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-panel p-5">
        <span className="text-sm">{t('settings.signedInAs', { login: me.login })}</span>
        <a
          href="/auth/logout"
          className="inline-flex min-h-11 items-center rounded-lg border border-line-strong bg-panel-raised px-4 text-sm font-semibold"
        >
          {t('app.logout')}
        </a>
      </section>
    </div>
  )
}
