import { useEffect, useState } from 'react'

export type Route =
  | { view: 'home' }
  | { view: 'channel' }
  | { view: 'audience' }
  | { view: 'money' }
  | { view: 'settings' }
  | { view: 'stream'; streamId: number }
  | { view: 'search'; query: string }

type StaticRoute = Extract<Route, { view: 'channel' | 'audience' | 'money' | 'settings' }>

// The old names stay as aliases: help pages and bookmarks still point at them.
const STATIC_ROUTES: Record<string, StaticRoute> = {
  channel: { view: 'channel' },
  audience: { view: 'audience' },
  followers: { view: 'audience' },
  money: { view: 'money' },
  finance: { view: 'money' },
  settings: { view: 'settings' },
}

export function parseHash(hash: string): Route {
  const clean = hash.replace(/^#\/?/, '')
  if (Object.hasOwn(STATIC_ROUTES, clean)) {
    return STATIC_ROUTES[clean]
  }
  const streamMatch = clean.match(/^stream\/(\d+)/)
  if (streamMatch) {
    return { view: 'stream', streamId: Number(streamMatch[1]) }
  }
  const searchMatch = clean.match(/^search\?q=(.*)$/)
  if (searchMatch) {
    return { view: 'search', query: decodeURIComponent(searchMatch[1]) }
  }
  return { view: 'home' }
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
