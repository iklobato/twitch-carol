import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { setLang } from '../i18n'
import type { Me } from '../types'
import DigestSettings from './DigestSettings'

afterEach(() => {
  vi.restoreAllMocks()
})

const me = {
  email: 'streamer@example.com',
  digest_weekly: true,
  digest_monthly: true,
} as unknown as Me

describe('DigestSettings', () => {
  it('patches digest_weekly when the weekly checkbox is unchecked', async () => {
    setLang('en')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true } as Response)
    vi.stubGlobal('fetch', fetchMock)
    render(<DigestSettings me={me} />)

    fireEvent.click(screen.getByLabelText(/weekly recap/i))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [path, init] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/channel/preferences')
    expect(JSON.parse(init.body)).toEqual({ digest_weekly: false })
  })

  it('patches digest_monthly independently of the weekly flag', async () => {
    setLang('en')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true } as Response)
    vi.stubGlobal('fetch', fetchMock)
    render(<DigestSettings me={me} />)

    fireEvent.click(screen.getByLabelText(/monthly recap/i))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse(init.body)).toEqual({ digest_monthly: false })
  })

  it('warns when the channel has no email on file', () => {
    setLang('en')
    render(<DigestSettings me={{ ...me, email: null }} />)

    expect(screen.getByText(/no email on file/i)).toBeTruthy()
  })

  it('says nothing about a missing email when one is on file', () => {
    setLang('en')
    render(<DigestSettings me={me} />)

    expect(screen.queryByText(/no email on file/i)).toBeNull()
  })
})
