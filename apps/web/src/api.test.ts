import { describe, expect, it } from 'vitest'
import { statusLabel } from './api'
import { setLang } from './i18n'

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

describe('statusLabel', () => {
  it('has a label for every backend status, in both languages', () => {
    for (const lang of ['en', 'pt']) {
      setLang(lang)
      for (const status of BACKEND_STATUSES) {
        expect(statusLabel(status), `missing label for ${status} in ${lang}`).not.toBe(
          status,
        )
      }
    }
    setLang('en')
  })

  it('falls back to the raw value for a status it does not know', () => {
    setLang('en')
    expect(statusLabel('some_new_status')).toBe('some_new_status')
  })
})
