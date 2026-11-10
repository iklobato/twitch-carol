import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { setLang } from '../i18n'
import type { Me } from '../types'
import SettingsView from './SettingsView'

function makeMe(overrides: Partial<Me> = {}): Me {
  return {
    twitch_user_id: 1,
    login: 'iklobat',
    display_name: 'iklobat',
    scopes: [],
    is_admin: false,
    language: 'en',
    needs_onboarding: false,
    stream_language: 'pt',
    timezone: 'America/Sao_Paulo',
    impersonating: null,
    email: 'streamer@example.com',
    digest_weekly: true,
    digest_monthly: false,
    ...overrides,
  }
}

beforeEach(() => {
  setLang('en')
})

describe('SettingsView', () => {
  it('lista as permissoes que o streamer deu, com o nome legivel', () => {
    render(<SettingsView me={makeMe({ scopes: ['bits:read', 'moderator:read:followers'] })} />)

    expect(screen.getByText('Bits')).toBeTruthy()
    expect(screen.getByText('Followers')).toBeTruthy()
  })

  it('sem permissoes guardadas, nao mostra o bloco vazio', () => {
    render(<SettingsView me={makeMe({ scopes: [] })} />)

    expect(screen.queryByText('Data you allowed Stream Intel to read')).toBeNull()
  })

  it('mostra quem esta logado e o link de sair', () => {
    render(<SettingsView me={makeMe()} />)

    expect(screen.getByText('Signed in as @iklobat')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Log out' }).getAttribute('href')).toBe('/auth/logout')
  })
})
