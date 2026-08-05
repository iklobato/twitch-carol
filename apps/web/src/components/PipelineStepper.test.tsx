import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { QueueItem } from '../types'
import PipelineStepper from './PipelineStepper'

const queueItem: QueueItem = {
  stream_id: 1,
  job_type: 'transcribe',
  status: 'queued',
  position: 3,
  jobs_ahead: 2,
  eta_seconds: 300,
}

describe('PipelineStepper', () => {
  it('não renderiza nada quando a live está pronta', () => {
    const { container } = render(<PipelineStepper status="ready" queue={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('mostra captura ativa com os eventos de início e fim', () => {
    render(<PipelineStepper status="capturing" queue={null} />)
    expect(screen.getByText('Live being processed')).toBeTruthy()
    expect(screen.getByText('starts: stream.online')).toBeTruthy()
    expect(screen.getByText('ends: stream.offline')).toBeTruthy()
  })

  it('mostra posição e estimativa quando na fila', () => {
    render(<PipelineStepper status="queued_transcription" queue={queueItem} />)
    expect(screen.getByText('Transcription · queued')).toBeTruthy()
    expect(screen.getByText(/position 3/)).toBeTruthy()
    expect(screen.getByText(/~5 min/)).toBeTruthy()
  })

  it('análise ativa mostra a dependência da transcrição', () => {
    render(<PipelineStepper status="analyzing" queue={null} />)
    expect(screen.getByText('needs: transcription done')).toBeTruthy()
    expect(screen.getByText('ends: insights validated')).toBeTruthy()
  })

  it('estado de falha aparece em destaque', () => {
    render(<PipelineStepper status="failed" queue={null} />)
    expect(screen.getByText('Processing failed')).toBeTruthy()
  })
})
