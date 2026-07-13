import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ChatterOut } from '../types'
import ChattersSection from './ChattersSection'

function makeChatters(count: number, overrides: Partial<ChatterOut>[] = []): ChatterOut[] {
  return Array.from({ length: count }, (_, index) => ({
    author_login: `viewer_${index}`,
    messages: 100 - index,
    pct_of_total: 5,
    first_at: '2026-07-11T20:00:00Z',
    last_at: '2026-07-11T20:20:00Z',
    active_minutes: 10,
    peak_messages: 0,
    sentiment_score: 0,
    followed_during_stream: false,
    labels: [],
    sample_messages: [],
    top_words: [],
    ...overrides[index],
  }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function mockChatters(count: number) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(makeChatters(count)), { status: 200 })),
  )
}

describe('ChattersSection', () => {
  it('mostra 5 por página e navega', async () => {
    mockChatters(12)
    render(<ChattersSection streamId={6} />)
    await screen.findByText('viewer_0')

    expect(screen.getByText('viewer_4')).toBeTruthy()
    expect(screen.queryByText('viewer_5')).toBeNull()
    expect(screen.getByText('página 1 de 3')).toBeTruthy()
    expect(screen.getByRole('button', { name: '‹ anteriores' })).toHaveProperty('disabled', true)

    fireEvent.click(screen.getByRole('button', { name: 'próximos ›' }))
    expect(screen.getByText('viewer_5')).toBeTruthy()
    expect(screen.queryByText('viewer_0')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'próximos ›' }))
    expect(screen.getByText('página 3 de 3')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'próximos ›' })).toHaveProperty('disabled', true)
  })

  it('sem paginação quando cabe numa página', async () => {
    mockChatters(4)
    render(<ChattersSection streamId={6} />)
    await screen.findByText('viewer_0')
    expect(screen.queryByText(/página/)).toBeNull()
  })

  it('não renderiza nada sem chatters', async () => {
    mockChatters(0)
    const { container } = render(<ChattersSection streamId={6} />)
    await waitFor(() => expect(container.firstChild).toBeNull())
  })

  it('reordena por sentimento ao trocar o filtro', async () => {
    // viewer_0 has most messages but lowest sentiment; viewer_2 the highest
    const data = makeChatters(3, [
      { sentiment_score: -0.5 },
      { sentiment_score: 0.1 },
      { sentiment_score: 0.9 },
    ])
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(data), { status: 200 })))
    render(<ChattersSection streamId={6} />)
    await screen.findByText('viewer_0')

    // default order (messages): viewer_0 first
    const rowsByMessages = screen.getAllByRole('button', { name: /viewer_/ })
    expect(rowsByMessages[0].textContent).toBe('viewer_0')

    fireEvent.click(screen.getByRole('button', { name: 'Sentimento' }))
    const rowsBySentiment = screen.getAllByRole('button', { name: /viewer_/ })
    expect(rowsBySentiment[0].textContent).toBe('viewer_2')
  })
})
