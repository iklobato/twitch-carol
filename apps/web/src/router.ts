import { useEffect, useState } from 'react'

export type Route =
  | { view: 'home' }
  | { view: 'stream'; streamId: number }
  | { view: 'search'; query: string }

export function parseHash(hash: string): Route {
  const clean = hash.replace(/^#\/?/, '')
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
