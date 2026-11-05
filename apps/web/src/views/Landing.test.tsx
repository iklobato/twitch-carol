import { render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { setLang } from '../i18n'
import Landing from './Landing'

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubReducedMotion(reduce: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: reduce, media: query }) as MediaQueryList)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false } as Response))
}

function heroVideo(container: HTMLElement): HTMLVideoElement {
  const video = container.querySelector<HTMLVideoElement>('header.hero video')
  if (!video) throw new Error('no video in the hero')
  return video
}

describe('Landing hero video', () => {
  it('starts on its own, muted, with controls to turn the sound on', () => {
    // Browsers refuse to autoplay a video with sound, so muted is what makes
    // autoplay work at all.
    setLang('en')
    stubReducedMotion(false)
    const video = heroVideo(render(<Landing />).container)

    expect(video.getAttribute('src')).toBe('/landing-demo.mp4')
    expect(video.hasAttribute('autoplay')).toBe(true)
    // jsdom does not turn the attribute into the muted state; a real browser does
    expect(video.hasAttribute('muted')).toBe(true)
    expect(video.hasAttribute('playsinline')).toBe(true)
    expect(video.hasAttribute('controls')).toBe(true)
    expect(video.getAttribute('aria-label')).toBe('Stream Intel demo video')
  })

  it('does not start on its own for visitors who ask for less motion', () => {
    setLang('en')
    stubReducedMotion(true)
    const video = heroVideo(render(<Landing />).container)

    expect(video.hasAttribute('autoplay')).toBe(false)
    expect(video.getAttribute('poster')).toBe('/landing-demo.jpg')
  })
})
