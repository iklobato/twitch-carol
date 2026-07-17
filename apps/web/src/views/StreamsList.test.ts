import { describe, expect, it } from 'vitest'
import type { StreamListItem } from '../types'
import { dayTotals, groupByDay } from './StreamsList'

function live(id: number, day: string, over: Partial<StreamListItem> = {}): StreamListItem {
  return {
    id,
    started_at: `${day}T12:00:00`,
    ended_at: null,
    title: null,
    category: null,
    status: 'ready',
    messages: 0,
    chatters: 0,
    events: 0,
    followers: 0,
    peak_viewers: 0,
    records: [],
    day,
    ...over,
  }
}

describe('groupByDay', () => {
  it('agrupa lives do mesmo dia e separa dias diferentes', () => {
    const streams = [live(3, '2026-07-17'), live(2, '2026-07-17'), live(1, '2026-07-16')]
    const groups = groupByDay(streams)
    expect(groups).toHaveLength(2)
    expect(groups[0].streams.map((s) => s.id)).toEqual([3, 2])
    expect(groups[1].streams.map((s) => s.id)).toEqual([1])
  })
})

describe('dayTotals', () => {
  it('soma mensagens/eventos/seguidores, pega o maior pico e usa chatters únicos do backend', () => {
    const streams = [
      live(1, '2026-07-15', { messages: 300, events: 5, followers: 0, peak_viewers: 17 }),
      live(2, '2026-07-15', { messages: 110, events: 2, followers: 0, peak_viewers: 12 }),
    ]
    expect(dayTotals(streams, 26)).toEqual({
      messages: 410,
      chatters: 26,
      events: 7,
      followers: 0,
      peak_viewers: 17,
    })
  })
})
