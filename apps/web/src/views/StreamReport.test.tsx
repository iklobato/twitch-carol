import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import StreamReport from './StreamReport'

// chart.js needs a real canvas; the chart itself is out of scope here
vi.mock('../components/TimelineChart', () => ({
  default: () => <div data-testid="chart" />,
}))

const report = {
  id: 6,
  started_at: '2026-07-11T20:00:00Z',
  ended_at: '2026-07-11T20:20:00Z',
  title: 'Live de teste',
  category: null,
  status: 'ready',
  audit: null,
  numbers: {
    messages: { value: 100, previous_avg: 50, delta_pct: 100 },
  },
  peaks: [
    {
      id: 9,
      window_start: '2026-07-11T20:10:00Z',
      window_end: '2026-07-11T20:11:00Z',
      metric: 'chat_rate',
      score: 4.2,
    },
  ],
  insights: [
    {
      id: 77,
      type: 'summary',
      content: 'Resumo da live de teste.',
      evidence: { segment_ids: [1] },
      feedback: null,
      cited_messages: [],
      cited_segments: [
        { id: 1, started_at: '2026-07-11T20:01:00Z', text: 'primeiro trecho citado' },
      ],
      engagement_pct: null,
    },
    {
      id: 78,
      type: 'peak_explanation',
      content: 'O chat explodiu com a raid.',
      evidence: { peak_id: 9, message_ids: [5] },
      feedback: null,
      cited_messages: [
        { id: 5, sent_at: '2026-07-11T20:10:10Z', author_login: 'fan', text: 'HYPE' },
      ],
      cited_segments: [],
      engagement_pct: null,
    },
  ],
}

function mockFetch() {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      if (init?.method === 'POST') {
        return new Response(null, { status: 204 })
      }
      const body = url.startsWith('/api/streams/6/timeline')
        ? { chat: [], viewers: [], events: [], peaks: [] }
        : url.startsWith('/api/queue')
          ? []
          : report
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('StreamReport', () => {
  it('renderiza resumo, números e chips de evidência', async () => {
    mockFetch()
    render(<StreamReport streamId={6} />)
    expect(await screen.findByText('Resumo da live de teste.')).toBeTruthy()
    expect(screen.getByText(/100%/)).toBeTruthy()
    const chip = screen.getByRole('button', { name: /primeiro trecho citado/ })
    fireEvent.click(chip)
    expect(screen.getByText('primeiro trecho citado')).toBeTruthy()
  })

  it('botão útil envia o feedback correto e marca o estado', async () => {
    const calls = mockFetch()
    render(<StreamReport streamId={6} />)
    await screen.findByText('Resumo da live de teste.')

    const useful = screen.getAllByRole('button', { name: /Útil/ })[0]
    fireEvent.click(useful)

    await waitFor(() => {
      const post = calls.find((call) => call.init?.method === 'POST')
      expect(post?.url).toBe('/api/insights/77/feedback')
      expect(JSON.parse(String(post?.init?.body))).toEqual({ feedback: 'useful' })
    })
  })

  it('momento do pico mostra explicação e mensagens citadas ao clicar', async () => {
    mockFetch()
    render(<StreamReport streamId={6} />)
    await screen.findByText('O chat explodiu com a raid.')

    fireEvent.click(screen.getByRole('button', { name: /1 mensagens citadas/ }))
    expect(screen.getByText(/HYPE/)).toBeTruthy()
  })
})
