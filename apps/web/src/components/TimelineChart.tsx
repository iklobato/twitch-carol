import {
  CategoryScale,
  Chart,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
} from 'chart.js'
import { useEffect, useRef } from 'react'
import { EVENT_LABELS, formatTime } from '../api'
import type { Timeline } from '../types'

Chart.register(
  LineController,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
)

export type TimelineSeries = {
  labels: string[]
  chatData: number[]
  viewersData: (number | null)[]
  eventsData: (number | null)[]
  eventsByIndex: Map<number, string[]>
  peakByLabel: Map<string, number>
  peakLabels: Set<string>
}

// Build every series onto ONE x-axis drawn from the union of chat and viewer
// timestamps (one label per minute, ordered by real time). Keying off chat
// alone dropped viewers and events that fell in chat-silent minutes; here chat
// is 0 in a silent minute, viewers span their own gaps, and each event snaps to
// its nearest label so none is lost. Pure, so it can be tested without a canvas.
export function buildTimelineSeries(timeline: Timeline): TimelineSeries {
  const msByLabel = new Map<string, number>()
  for (const point of [...timeline.chat, ...timeline.viewers]) {
    const label = formatTime(point.t)
    if (!msByLabel.has(label)) msByLabel.set(label, new Date(point.t).getTime())
  }
  const labels = [...msByLabel.entries()].sort((a, b) => a[1] - b[1]).map(([label]) => label)
  const labelMs = labels.map((label) => msByLabel.get(label) as number)

  const peakByLabel = new Map<string, number>()
  for (const peak of timeline.peaks) {
    for (const label of labels) {
      if (label >= formatTime(peak.window_start) && label < formatTime(peak.window_end)) {
        peakByLabel.set(label, peak.id)
      }
    }
  }
  const chatByLabel = new Map(timeline.chat.map((point) => [formatTime(point.t), point.value]))
  const viewersByLabel = new Map(timeline.viewers.map((point) => [formatTime(point.t), point.value]))

  const eventsByIndex = new Map<number, string[]>()
  for (const event of timeline.events) {
    const t = new Date(event.t).getTime()
    let nearest = 0
    let bestGap = Infinity
    labelMs.forEach((ms, index) => {
      const gap = Math.abs(ms - t)
      if (gap < bestGap) {
        bestGap = gap
        nearest = index
      }
    })
    const name = EVENT_LABELS[event.type] ?? event.type
    const text = event.amount != null ? `${name} (${event.amount})` : name
    eventsByIndex.set(nearest, [...(eventsByIndex.get(nearest) ?? []), text])
  }
  const peakLabels = new Set(
    timeline.peaks.flatMap((peak) =>
      labels.filter((l) => l >= formatTime(peak.window_start) && l < formatTime(peak.window_end)),
    ),
  )

  return {
    labels,
    chatData: labels.map((l) => chatByLabel.get(l) ?? 0),
    viewersData: labels.map((l) => viewersByLabel.get(l) ?? null),
    eventsData: labels.map((_, index) => (eventsByIndex.has(index) ? 0 : null)),
    eventsByIndex,
    peakByLabel,
    peakLabels,
  }
}

export default function TimelineChart({
  timeline,
  onPeakClick,
}: {
  timeline: Timeline
  onPeakClick?: (peakId: number) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const chartRef = useRef<Chart | null>(null)

  useEffect(() => {
    if (!canvasRef.current) return
    const { labels, chatData, viewersData, eventsData, eventsByIndex, peakByLabel, peakLabels } =
      buildTimelineSeries(timeline)

    chartRef.current?.destroy()
    chartRef.current = new Chart(canvasRef.current, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Mensagens/min',
            data: chatData,
            borderColor: '#a855f7',
            backgroundColor: '#a855f7',
            pointRadius: labels.map((l) => (peakLabels.has(l) ? 5 : 2)),
            pointBackgroundColor: labels.map((l) => (peakLabels.has(l) ? '#f97316' : '#a855f7')),
            tension: 0.3,
            yAxisID: 'y',
          },
          {
            label: 'Viewers',
            data: viewersData,
            borderColor: '#38bdf8',
            backgroundColor: '#38bdf8',
            pointRadius: 2,
            tension: 0.3,
            spanGaps: true,
            yAxisID: 'y1',
          },
          {
            label: 'Eventos',
            data: eventsData,
            showLine: false,
            pointStyle: 'triangle',
            pointRadius: 7,
            borderColor: '#facc15',
            backgroundColor: '#facc15',
            yAxisID: 'y',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: '#d4d4d8' } },
          tooltip: {
            callbacks: {
              afterBody: (items) => {
                const index = items[0]?.dataIndex
                return index != null ? (eventsByIndex.get(index) ?? []) : []
              },
            },
          },
        },
        onClick: (_event, elements) => {
          if (!onPeakClick || elements.length === 0) return
          const label = labels[elements[0].index]
          const peakId = peakByLabel.get(label)
          if (peakId !== undefined) onPeakClick(peakId)
        },
        onHover: (event, elements) => {
          const target = event.native?.target as HTMLElement | undefined
          if (target) {
            const label = elements.length > 0 ? labels[elements[0].index] : undefined
            target.style.cursor = label && peakByLabel.has(label) ? 'pointer' : 'default'
          }
        },
        scales: {
          x: { ticks: { color: '#71717a', maxTicksLimit: 12 }, grid: { color: '#27272a' } },
          y: {
            title: { display: true, text: 'msgs/min', color: '#71717a' },
            ticks: { color: '#71717a' },
            grid: { color: '#27272a' },
          },
          y1: {
            position: 'right',
            title: { display: true, text: 'viewers', color: '#71717a' },
            ticks: { color: '#71717a' },
            grid: { drawOnChartArea: false },
          },
        },
      },
    })
    return () => chartRef.current?.destroy()
  }, [timeline, onPeakClick])

  return (
    <div className="h-72 w-full">
      <canvas ref={canvasRef} />
    </div>
  )
}
