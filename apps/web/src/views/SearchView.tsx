import { useEffect, useState } from 'react'
import { apiGet, formatDate, formatTime } from '../api'
import type { SearchHit } from '../types'

export default function SearchView({ query }: { query: string }) {
  const [hits, setHits] = useState<SearchHit[] | null>(null)

  useEffect(() => {
    if (query.length < 2) return
    setHits(null)
    apiGet<SearchHit[]>(`/api/search?q=${encodeURIComponent(query)}`).then(setHits)
  }, [query])

  if (query.length < 2) return <p className="text-zinc-400">Digite pelo menos 2 caracteres.</p>
  if (hits === null) return <p className="text-zinc-400">Buscando "{query}"...</p>

  return (
    <div>
      <h2 className="mb-4 text-xl font-bold">
        Busca por "{query}" · {hits.length} resultado(s)
      </h2>
      <div className="space-y-2">
        {hits.map((hit, index) => (
          <a
            key={index}
            href={`#/stream/${hit.stream_id}`}
            className="block rounded-lg border border-zinc-800 bg-zinc-900 p-3 hover:border-zinc-600"
          >
            <p className="text-xs text-zinc-500">
              {hit.source === 'chat' ? `💬 chat (${hit.author_login})` : '🎙️ transcrição'} · live #
              {hit.stream_id} · {formatDate(hit.at)} {formatTime(hit.at)}
            </p>
            <p className="text-sm">{hit.text}</p>
          </a>
        ))}
      </div>
    </div>
  )
}
