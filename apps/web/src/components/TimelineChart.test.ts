import { describe, expect, it } from 'vitest'
import type { Timeline } from '../types'
import { buildTimelineSeries } from './TimelineChart'

// A quiet stream: chat only in minute 2, but viewers sampled every minute and
// two events land in chat-silent minutes. All of them must still appear.
const timeline: Timeline = {
  chat: [{ t: '2026-01-01T00:02:00Z', value: 5 }],
  viewers: [0, 1, 2, 3, 4].map((m) => ({
    t: `2026-01-01T00:0${m}:00Z`,
    value: [60, 100, 40, 40, 70][m],
  })),
  events: [
    { t: '2026-01-01T00:00:30Z', type: 'channel.follow', amount: null },
    { t: '2026-01-01T00:04:15Z', type: 'channel.ad_break.begin', amount: 90 },
  ],
  peaks: [],
}

describe('buildTimelineSeries', () => {
  it('keeps every viewer sample even when chat is silent', () => {
    const { labels, viewersData } = buildTimelineSeries(timeline)
    expect(labels).toHaveLength(5) // one per minute, from chat ∪ viewers
    // all five viewer values present (the old chat-keyed chart dropped four)
    expect(viewersData).toEqual([60, 100, 40, 40, 70])
  })

  it('plots chat as 0 in minutes without messages', () => {
    const { chatData } = buildTimelineSeries(timeline)
    expect(chatData).toEqual([0, 0, 5, 0, 0])
  })

  it('snaps every event to its nearest label so none is dropped', () => {
    const { eventsData, eventsByIndex } = buildTimelineSeries(timeline)
    // follow -> minute 0, ad break -> minute 4
    expect(eventsData[0]).toBe(0)
    expect(eventsData[4]).toBe(0)
    expect(eventsByIndex.get(4)?.[0]).toContain('90')
    expect(eventsData.filter((v) => v === 0)).toHaveLength(2)
  })
})
