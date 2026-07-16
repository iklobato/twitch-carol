import { describe, expect, it } from 'vitest'
import { parseHash } from './router'

describe('parseHash', () => {
  it('rota vazia e raiz vão para home', () => {
    expect(parseHash('')).toEqual({ view: 'home' })
    expect(parseHash('#/')).toEqual({ view: 'home' })
    expect(parseHash('#')).toEqual({ view: 'home' })
  })

  it('abre o relatório de uma live pelo id', () => {
    expect(parseHash('#/stream/42')).toEqual({ view: 'stream', streamId: 42 })
  })

  it('id não numérico cai na home', () => {
    expect(parseHash('#/stream/abc')).toEqual({ view: 'home' })
  })

  it('busca decodifica o termo da query', () => {
    expect(parseHash('#/search?q=autentica%C3%A7%C3%A3o')).toEqual({
      view: 'search',
      query: 'autenticação',
    })
  })

  it('abre a visão do canal', () => {
    expect(parseHash('#/channel')).toEqual({ view: 'channel' })
  })

  it('abre a visão do financeiro', () => {
    expect(parseHash('#/finance')).toEqual({ view: 'finance' })
  })

  it('rota desconhecida cai na home', () => {
    expect(parseHash('#/qualquer/coisa')).toEqual({ view: 'home' })
  })
})
