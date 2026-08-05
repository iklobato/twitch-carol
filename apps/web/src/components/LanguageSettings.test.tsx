import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { setLang } from '../i18n'
import type { Me } from '../types'
import LanguageSettings from './LanguageSettings'

afterEach(() => {
  vi.restoreAllMocks()
})

const me = {
  language: 'en',
  stream_language: 'en',
  timezone: 'America/Sao_Paulo',
} as unknown as Me

describe('LanguageSettings', () => {
  it('sends both languages when the streamer changes one', async () => {
    setLang('en')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true } as Response)
    vi.stubGlobal('fetch', fetchMock)
    render(<LanguageSettings me={me} />)

    fireEvent.change(screen.getByLabelText(/stream in/i), { target: { value: 'pt' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [path, init] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/channel/preferences')
    expect(JSON.parse(init.body)).toEqual({
      stream_language: 'pt',
      screen_language: 'en',
    })
  })

  it('says the screen language only applies after a reload', async () => {
    // setLang runs once at boot, so claiming it changed on the spot would be a
    // lie the half-translated page immediately exposes.
    setLang('en')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true } as Response))
    render(<LanguageSettings me={me} />)

    fireEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => expect(screen.getByText(/reload/i)).toBeTruthy())
  })
})
