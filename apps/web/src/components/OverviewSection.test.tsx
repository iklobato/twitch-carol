import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type {
  ChannelOverview,
  FollowersOverview,
  StreamListItem,
} from '../types'
import OverviewSection, { chatPath, pickAttention } from './OverviewSection'

// Minimal builders: pickAttention only reads a few fields, so we populate those
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

describe('pickAttention', () => {
  it('lista todos os riscos e metas, risco primeiro', () => {
    const items = pickAttention(
      followers({ spike: true, suspicious: 12 }),
      channel({ goals: [{ pct: 90, current_amount: 90, target_amount: 100, description: 'x' }] }),
    )
    expect(items.map((item) => item.tone)).toEqual(['risk', 'risk', 'goal'])
    expect(items[1].text).toContain('12')
  })

  it('meta perto de bater mostra quanto falta e leva para Money', () => {
    const [item] = pickAttention(
      followers({}),
      channel({ goals: [{ pct: 85, current_amount: 850, target_amount: 1000, description: 'Seguidores' }] }),
    )
    expect(item.text).toContain('150')
    expect(item.href).toBe('#/money')
  })

  it('meta ja batida nao entra', () => {
    const items = pickAttention(
      followers({}),
      channel({ goals: [{ pct: 100, current_amount: 1000, target_amount: 1000, description: 'x' }] }),
    )
    expect(items).toEqual([])
  })

  it('poucos suspeitos e recomendacao da IA nao viram alerta', () => {
    expect(pickAttention(followers({ suspicious: 9 }), channel({ recos: ['faça y'] }))).toEqual([])
  })
})

describe('chatPath', () => {
  it('o ponto mais alto encosta no topo e o zero no fundo', () => {
    const path = chatPath(
      [
        { t: 'a', value: 0 },
        { t: 'b', value: 10 },
        { t: 'c', value: 5 },
      ],
      100,
      50,
    )
    expect(path).toBe('M0.0 50.0 L50.0 0.0 L100.0 25.0')
  })

  it('menos de dois pontos nao desenha nada', () => {
    expect(chatPath([{ t: 'a', value: 3 }], 100, 50)).toBe('')
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
  day: '2026-07-08',
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
              : url.includes('/api/streams/7/timeline')
                ? { chat: [{ t: 'a', value: 1 }, { t: 'b', value: 4 }], viewers: [], events: [], peaks: [] }
                : url.includes('/api/streams/7')
                ? { numbers: { messages: { value: 1200, previous_avg: 1000, delta_pct: 20 } } }
                : {}
        return new Response(JSON.stringify(body), { status: 200 })
      }),
    )

    render(<OverviewSection streams={[READY_STREAM]} />)

    await screen.findByText('Overview')
    expect(screen.getByText('12,400')).toBeTruthy() // followers
    expect(screen.getByText((t) => t.includes('546.00'))).toBeTruthy() // earned
    expect(screen.getByText('Speedrun de Elden Ring')).toBeTruthy() // last live
    await waitFor(() =>
      expect(screen.getByText((t) => t.includes('Just Chatting'))).toBeTruthy(),
    ) // proximo passo = recomendacao da IA
    expect(await screen.findByRole('img', { name: 'Messages/min' })).toBeTruthy() // grafico da ultima live
  })
})
