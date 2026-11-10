import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { setLang } from '../i18n'
import Sidebar from './Sidebar'

beforeEach(() => {
  setLang('en')
})

describe('Sidebar', () => {
  it('marca so a tela aberta como pagina atual', () => {
    render(<Sidebar route={{ view: 'money' }} />)

    const current = screen.getAllByRole('link').filter((link) => link.getAttribute('aria-current') === 'page')
    expect(current.map((link) => link.textContent)).toEqual(['Money'])
  })

  it('relatorio de uma live deixa Home acesa', () => {
    render(<Sidebar route={{ view: 'stream', streamId: 7 }} />)

    expect(screen.getByRole('link', { name: 'Home' }).getAttribute('aria-current')).toBe('page')
  })
})
