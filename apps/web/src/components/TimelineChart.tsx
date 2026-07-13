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
    const labels = timeline.chat.map((point) => formatTime(point.t))
    // map each x label inside a peak window to that peak's id, for click-to-jump
    const peakByLabel = new Map<string, number>()
    for (const peak of timeline.peaks) {
      for (const label of labels) {
        if (label >= formatTime(peak.window_start) && label < formatTime(peak.window_end)) {
          peakByLabel.set(label, peak.id)
        }
      }
    }
    const viewersByLabel = new Map(
      timeline.viewers.map((point) => [formatTime(point.t), point.value]),
    )
    const eventsByLabel = new Map<string, string[]>()
    for (const event of timeline.events) {
      const label = formatTime(event.t)
      const name = EVENT_LABELS[event.type] ?? event.type
      const text = event.amount != null ? `${name} (${event.amount})` : name
      eventsByLabel.set(label, [...(eventsByLabel.get(label) ?? []), text])
    }
    const peakLabels = new Set(
      timeline.peaks.flatMap((peak) =>
        labels.filter((l) => l >= formatTime(peak.window_start) && l < formatTime(peak.window_end)),
      ),
    )

    chartRef.current?.destroy()
    chartRef.current = new Chart(canvasRef.current, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Mensagens/min',
            data: timeline.chat.map((point) => point.value),
            borderColor: '#a855f7',
            backgroundColor: '#a855f7',
            pointRadius: labels.map((l) => (peakLabels.has(l) ? 5 : 2)),
            pointBackgroundColor: labels.map((l) => (peakLabels.has(l) ? '#f97316' : '#a855f7')),
            tension: 0.3,
            yAxisID: 'y',
          },
          {
            label: 'Viewers',
            data: labels.map((l) => viewersByLabel.get(l) ?? null),
            borderColor: '#38bdf8',
            backgroundColor: '#38bdf8',
            pointRadius: 2,
            tension: 0.3,
            spanGaps: true,
            yAxisID: 'y1',
          },
          {
            label: 'Eventos',
            data: labels.map((l) => (eventsByLabel.has(l) ? 0 : null)),
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
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: '#d4d4d8' } },
          tooltip: {
            callbacks: {
              afterBody: (items) => {
                const label = items[0]?.label
                return label ? (eventsByLabel.get(label) ?? []) : []
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

  return <canvas ref={canvasRef} className="max-h-72 w-full" />
}
