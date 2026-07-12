import { describe, expect, it } from 'vitest'
import { STATUS_LABELS } from './api'

// must mirror core/models.py StreamStatus: a missing label would show the
// raw enum value in the UI
const BACKEND_STATUSES = [
  'capturing',
  'queued_transcription',
  'transcribing',
  'queued_analysis',
  'analyzing',
  'ready',
  'failed',
]

describe('STATUS_LABELS', () => {
  it('cobre todos os status do backend', () => {
    for (const status of BACKEND_STATUSES) {
      expect(STATUS_LABELS[status], `label ausente para ${status}`).toBeTruthy()
    }
  })
})
