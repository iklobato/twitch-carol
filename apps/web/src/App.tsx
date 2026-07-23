import { useEffect, useState } from 'react'
import { useRoute } from './router'
import ChannelView from './views/ChannelView'
import FinanceView from './views/FinanceView'
import FollowersView from './views/FollowersView'
import Landing from './views/Landing'
import StreamReport from './views/StreamReport'
import StreamsList from './views/StreamsList'
import SearchView from './views/SearchView'
import type { ChannelOption, Me } from './types'

function SearchBox() {
  const [value, setValue] = useState('')
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (value.trim().length >= 2) {
          window.location.hash = `#/search?q=${encodeURIComponent(value.trim())}`
        }
      }}
    >
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Buscar no chat e na fala..."
        className="w-64 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm placeholder-zinc-500 focus:border-purple-500 focus:outline-none"
      />
    </form>
  )
}

function ImpersonatePicker() {
  const [options, setOptions] = useState<ChannelOption[] | null>(null)
  useEffect(() => {
    fetch('/api/admin/channels')
      .then((response) => (response.ok ? response.json() : []))
      .then(setOptions)
      .catch(() => setOptions([]))
  }, [])

  async function impersonate(login: string) {
    if (!login) return
    await fetch(`/api/admin/impersonate/${login}`, { method: 'POST' })
    window.location.reload()
  }

  if (!options || options.length === 0) return null
  return (
    <select
      defaultValue=""
      onChange={(event) => impersonate(event.target.value)}
      className="rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-300 focus:border-purple-500 focus:outline-none"
    >
      <option value="" disabled>
        Impersonar...
      </option>
      {options.map((option) => (
        <option key={option.login} value={option.login}>
          {option.display_name} (@{option.login})
        </option>
      ))}
    </select>
  )
}

function ImpersonationBanner({ login }: { login: string }) {
  async function stop() {
    await fetch('/api/admin/impersonate/stop', { method: 'POST' })
    window.location.reload()
  }
  return (
    <div className="flex items-center justify-center gap-3 bg-red-700 px-4 py-2 text-sm text-white">
      <span>
        Vendo como <strong>@{login}</strong>
      </span>
      <button onClick={stop} className="rounded bg-red-900 px-2 py-0.5 hover:bg-red-950">
        Sair
      </button>
    </div>
  )
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const route = useRoute()

  useEffect(() => {
    fetch('/api/me')
      .then((response) => (response.ok ? response.json() : null))
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <div className="min-h-screen bg-zinc-950 p-8 text-zinc-400">Carregando...</div>
  }
  if (!me) {
    return <Landing />
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      {me.impersonating && <ImpersonationBanner login={me.impersonating.as_login} />}
      <header className="border-b border-zinc-800 bg-zinc-900">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-4">
            <a href="#/" className="text-lg font-bold">
              Stream Intel
            </a>
            <a href="#/channel" className="text-sm text-zinc-400 hover:text-purple-300">
              Meu canal
            </a>
            <a href="#/followers" className="text-sm text-zinc-400 hover:text-purple-300">
              Meus seguidores
            </a>
            <a href="#/finance" className="text-sm text-zinc-400 hover:text-purple-300">
              Financeiro
            </a>
          </div>
          <SearchBox />
          <div className="flex items-center gap-3 text-sm">
            {!me.streamelements_connected && (
              <a
                href="/api/integrations/streamelements/connect"
                className="rounded-lg border border-purple-600 bg-purple-600/20 px-3 py-1.5 font-semibold text-purple-200 hover:bg-purple-600/40"
              >
                Conectar StreamElements
              </a>
            )}
            {me.is_admin && <ImpersonatePicker />}
            <span className="text-zinc-400">@{me.login}</span>
            <a href="/auth/logout" className="text-zinc-500 underline hover:text-zinc-300">
              Sair
            </a>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">
        {route.view === 'home' && <StreamsList />}
        {route.view === 'channel' && <ChannelView />}
        {route.view === 'followers' && <FollowersView />}
        {route.view === 'finance' && <FinanceView />}
        {route.view === 'stream' && <StreamReport streamId={route.streamId} />}
        {route.view === 'search' && <SearchView query={route.query} />}
      </main>
    </div>
  )
}
