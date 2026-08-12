import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { setLang } from '../i18n'
import Onboarding from './Onboarding'

afterEach(() => {
  vi.restoreAllMocks()
})

function mockFetch(ok: boolean) {
  const fetchMock = vi.fn().mockResolvedValue({ ok } as Response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('Onboarding', () => {
  it('sends the declared language and reports back', async () => {
    setLang('en')
    const fetchMock = mockFetch(true)
    const onDone = vi.fn()
    render(<Onboarding onDone={onDone} />)

    fireEvent.change(screen.getByLabelText(/stream in/i), { target: { value: 'pt' } })
    fireEvent.click(screen.getByRole('button', { name: /start/i }))

    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const [path, init] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/channel/preferences')
    expect(init.method).toBe('PATCH')
    // the zone rides along without being asked: it decides the best weekday and
    // hour to go live, and it defaulted to UTC for every channel until now
    const sent = JSON.parse(init.body)
    expect(sent.stream_language).toBe('pt')
    expect(sent.timezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone)
  })

  it('keeps the gate closed when saving fails', async () => {
    // Letting the streamer through on a failed save would leave the channel
    // with no declared language and no second chance to ask.
    setLang('en')
    mockFetch(false)
    const onDone = vi.fn()
    render(<Onboarding onDone={onDone} />)

    fireEvent.click(screen.getByRole('button', { name: /start/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(onDone).not.toHaveBeenCalled()
  })
})
