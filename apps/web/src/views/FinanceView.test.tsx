import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FinanceOverview } from '../types'
import FinanceView from './FinanceView'

function makeFinance(overrides: Partial<FinanceOverview> = {}): FinanceOverview {
  return {
    period: '30d',
    estimated_usd: 0,
    tips_usd: 0,
    tips_count: 0,
    merch_usd: 0,
    total_revenue_usd: 0,
    streamed_hours: 0,
    revenue_per_hour_usd: 0,
    delta_pct: null,
    total_bits: 0,
    total_subs: 0,
    total_gifts: 0,
    money_events: 0,
    top_contributors: [],
    by_stream: [],
    by_content: [],
    engagement: {
      hype_train: { count: 0, best_level: 0, total_contributed: 0 },
      top_rewards: [],
      ads: { breaks: 0, total_seconds: 0, avg_viewer_change_pct: null },
    },
    subscribers: { total: 0, tiers: [], gifted_pct: 0, subs_ended: 0, top_bits: [] },
    goals: [],
    recommendations: [],
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FinanceView', () => {
  it('mostra arrecadado e o delta vs o período anterior', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        url.startsWith('/api/finance?')
          ? new Response(
              JSON.stringify(
                makeFinance({ estimated_usd: 15, delta_pct: 50, total_bits: 1000, money_events: 2 }),
              ),
              { status: 200 },
            )
          : new Response('[]', { status: 200 }),
      ),
    )
    render(<FinanceView />)

    await screen.findByText((text) => text.includes('50%'))
    expect(screen.getByText('1.000')).toBeTruthy()
  })

  it('trocar o período refaz o fetch com o novo recorte', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (!url.startsWith('/api/finance?')) return new Response('[]', { status: 200 })
      const usd = url.includes('period=90d') ? 90 : 30
      return new Response(JSON.stringify(makeFinance({ estimated_usd: usd, money_events: 1 })), {
        status: 200,
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<FinanceView />)

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/finance?period=30d'),
    )

    fireEvent.click(screen.getByRole('button', { name: '90 dias' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/finance?period=90d'),
    )
  })

  it('mostra apoiadores, superfãs e ranking do StreamElements', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.startsWith('/api/finance/supporters'))
          return new Response(
            JSON.stringify([
              { tipper: 'alice', total: 25, currency: 'USD', tips_count: 2, last_tipped_at: 'x' },
            ]),
            { status: 200 },
          )
        if (url.startsWith('/api/finance/loyalty'))
          return new Response(JSON.stringify([{ username: 'bob', points: 500, rank: 1 }]), {
            status: 200,
          })
        if (url.startsWith('/api/finance/top-people'))
          return new Response(
            JSON.stringify([{ name: 'carol', tips_usd: 25, loyalty_points: 900 }]),
            { status: 200 },
          )
        return new Response(JSON.stringify(makeFinance({ money_events: 1 })), { status: 200 })
      }),
    )
    render(<FinanceView />)

    await screen.findByText('Top apoiadores (tips)')
    expect(screen.getByText('Superfãs (fidelidade)')).toBeTruthy()
    expect(screen.getByText('Pessoas mais valiosas')).toBeTruthy()
    expect(screen.getByText('#1 bob')).toBeTruthy()
  })

  it('mostra o estado vazio quando nada foi monetizado', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(makeFinance()), { status: 200 })),
    )
    render(<FinanceView />)
    await screen.findByText((text) => text.includes('Nada monetizado'))
  })
})
