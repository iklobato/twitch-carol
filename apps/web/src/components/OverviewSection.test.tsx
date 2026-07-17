import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type {
  ChannelOverview,
  FollowersOverview,
  StreamListItem,
} from '../types'
import OverviewSection, { pickHighlight } from './OverviewSection'

// Minimal builders: pickHighlight only reads a few fields, so we populate those
// and cast (test-only) instead of constructing the full API payloads.
function followers(opts: {
  spike?: boolean
  suspicious?: number
  total?: number
  new30?: number
}): FollowersOverview {
  return {
    kpis: { total: opts.total ?? 1000, new_30d: opts.new30 ?? 0 },
    signals: {
      velocity: opts.spike ? [{ day: '2026-07-15', follows: 40, is_spike: true }] : [],
      suspicious_total: opts.suspicious ?? 0,
    },
  } as unknown as FollowersOverview
}

function channel(opts: {
  goals?: { pct: number; current_amount: number; target_amount: number; description: string }[]
  recos?: string[]
  subs?: number
  streams?: number
}): ChannelOverview {
  return {
    total_streams: opts.streams ?? 5,
    growth: [{ peak_viewers: 300 }, { peak_viewers: 500 }],
    subscribers: { total: opts.subs ?? 22, subs_ended: 0 },
    community: { goals: opts.goals ?? [] },
    recommendations: (opts.recos ?? []).map((content) => ({ content, facts: [] })),
  } as unknown as ChannelOverview
}

describe('pickHighlight', () => {
  it('prioriza risco de follow spike sobre meta e recomendação', () => {
    const h = pickHighlight(
      followers({ spike: true }),
      channel({ goals: [{ pct: 90, current_amount: 90, target_amount: 100, description: 'x' }], recos: ['faça y'] }),
    )
    expect(h?.tone).toBe('risk')
  })

  it('sinaliza muitos seguidores suspeitos', () => {
    const h = pickHighlight(followers({ suspicious: 12 }), channel({}))
    expect(h?.tone).toBe('risk')
    expect(h?.text).toContain('12')
  })

  it('mostra meta perto de bater quando não há risco', () => {
    const h = pickHighlight(
      followers({}),
      channel({ goals: [{ pct: 85, current_amount: 850, target_amount: 1000, description: 'Seguidores' }] }),
    )
    expect(h?.tone).toBe('goal')
    expect(h?.text).toContain('150')
  })

  it('cai na recomendação da IA quando não há risco nem meta perto', () => {
    const h = pickHighlight(followers({}), channel({ recos: ['Abra a semana com Just Chatting'] }))
    expect(h?.tone).toBe('reco')
    expect(h?.text).toContain('Just Chatting')
  })

  it('retorna null sem nada a destacar', () => {
    expect(pickHighlight(followers({}), channel({}))).toBeNull()
  })
})

const READY_STREAM: StreamListItem = {
  id: 7,
  started_at: '2026-07-08T20:00:00Z',
  ended_at: '2026-07-08T22:00:00Z',
  title: 'Speedrun de Elden Ring',
  category: 'Elden Ring',
  status: 'ready',
  messages: 1200,
  chatters: 340,
  events: 50,
  followers: 48,
  peak_viewers: 512,
  records: [],
}

afterEach(() => vi.unstubAllGlobals())

describe('OverviewSection', () => {
  it('renderiza KPIs, última live e destaque a partir dos endpoints', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const body = url.includes('/api/channel')
          ? channel({ subs: 22, streams: 11, recos: ['Abra a semana com Just Chatting'] })
          : url.includes('/api/followers')
            ? followers({ total: 12400, new30: 64 })
            : url.includes('/api/finance')
              ? { estimated_usd: 546, delta_pct: 77.3 }
              : url.includes('/api/streams/7')
                ? { numbers: { messages: { value: 1200, previous_avg: 1000, delta_pct: 20 } } }
                : {}
        return new Response(JSON.stringify(body), { status: 200 })
      }),
    )

    render(<OverviewSection streams={[READY_STREAM]} />)

    await screen.findByText('Visão geral')
    expect(screen.getByText('12.400')).toBeTruthy() // seguidores
    expect(screen.getByText((t) => t.includes('546,00'))).toBeTruthy() // arrecadado
    expect(screen.getByText('Speedrun de Elden Ring')).toBeTruthy() // última live
    await waitFor(() =>
      expect(screen.getByText((t) => t.includes('Just Chatting'))).toBeTruthy(),
    ) // destaque = recomendação
  })
})
