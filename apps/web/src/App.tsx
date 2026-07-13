import { useEffect, useState } from 'react'
import { useRoute } from './router'
import ChannelView from './views/ChannelView'
import StreamReport from './views/StreamReport'
import StreamsList from './views/StreamsList'
import SearchView from './views/SearchView'
import type { Me } from './types'

function LoginScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950 text-zinc-100">
      <div className="w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-900 p-8 text-center">
        <h1 className="mb-6 text-2xl font-bold">Stream Intel</h1>
        <p className="mb-6 text-zinc-400">
          Conecte sua conta da Twitch para começar a acompanhar suas lives.
        </p>
        <a
          href="/auth/login"
          className="inline-block rounded-lg bg-purple-600 px-6 py-3 font-semibold hover:bg-purple-500"
        >
          Conectar com a Twitch
        </a>
      </div>
    </div>
  )
}

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
    return <LoginScreen />
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="border-b border-zinc-800 bg-zinc-900">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-4">
            <a href="#/" className="text-lg font-bold">
              Stream Intel
            </a>
            <a href="#/channel" className="text-sm text-zinc-400 hover:text-purple-300">
              Meu canal
            </a>
          </div>
          <SearchBox />
          <div className="flex items-center gap-3 text-sm">
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
        {route.view === 'stream' && <StreamReport streamId={route.streamId} />}
        {route.view === 'search' && <SearchView query={route.query} />}
      </main>
    </div>
  )
}
