import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ChatterOut } from '../types'
import ChattersSection from './ChattersSection'

function makeChatters(count: number): ChatterOut[] {
  return Array.from({ length: count }, (_, index) => ({
    author_login: `viewer_${index}`,
    messages: 100 - index,
    pct_of_total: 5,
    first_at: '2026-07-11T20:00:00Z',
    last_at: '2026-07-11T20:20:00Z',
    active_minutes: 10,
    peak_messages: 0,
    followed_during_stream: false,
    labels: [],
    sample_messages: [],
    top_words: [],
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
})
