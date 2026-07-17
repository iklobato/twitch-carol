import { describe, expect, it } from 'vitest'
import type { StreamListItem } from '../types'
import { groupByDay } from './StreamsList'

function live(id: number, started_at: string): StreamListItem {
  return {
    id,
    started_at,
    ended_at: null,
    title: null,
    category: null,
    status: 'ready',
    messages: 0,
    chatters: 0,
    events: 0,
    followers: 0,
    peak_viewers: 0,
  } as StreamListItem
}

describe('groupByDay', () => {
  it('agrupa lives do mesmo dia e separa dias diferentes', () => {
    const streams = [
      live(3, '2026-07-17T22:00:00'),
      live(2, '2026-07-17T14:00:00'),
      live(1, '2026-07-16T20:00:00'),
    ]
    const groups = groupByDay(streams)
    expect(groups).toHaveLength(2)
    expect(groups[0].streams.map((s) => s.id)).toEqual([3, 2])
    expect(groups[1].streams.map((s) => s.id)).toEqual([1])
  })
})
