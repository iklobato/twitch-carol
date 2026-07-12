import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createRequire } from 'node:module';
import path from 'node:path';

const require = createRequire(import.meta.url);
const OVERLAY_PATH = path.resolve(__dirname, '../static/overlay.js');

const SHOW_MS = 6000;
const HIDE_MS = 600;
const RECONNECT_MS = 2000;

class FakeWebSocket {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.onmessage = null;
    this.onclose = null;
    FakeWebSocket.instances.push(this);
  }

  receive(data) {
    this.onmessage({ data });
  }

  drop() {
    this.onclose();
  }
}

function alertFrame(overrides = {}) {
  return JSON.stringify({
    kind: 'gift',
    headline: 'Ana presenteou 3 sub(s)!',
    detail: 'Tier 1 gift',
    username: 'Ana',
    amount: null,
    createdAt: '2026-01-01T00:00:00+00:00',
    ...overrides,
  });
}

let overlay;
let socket;
let box;
let headline;
let detail;

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
  document.body.innerHTML =
    '<div id="alert"><div id="headline"></div><div id="detail"></div></div>';
  delete require.cache[OVERLAY_PATH];
  overlay = require(OVERLAY_PATH);
  socket = FakeWebSocket.instances[0];
  box = document.getElementById('alert');
  headline = document.getElementById('headline');
  detail = document.getElementById('detail');
});

describe('alert playback', () => {
  it('shows an incoming alert and hides it after the display window', () => {
    socket.receive(alertFrame());
    expect(box.classList.contains('show')).toBe(true);
    expect(box.classList.contains('gift')).toBe(true);
    expect(headline.textContent).toBe('Ana presenteou 3 sub(s)!');
    expect(detail.textContent).toBe('Tier 1 gift');

    vi.advanceTimersByTime(SHOW_MS);
    expect(box.classList.contains('show')).toBe(false);

    vi.advanceTimersByTime(HIDE_MS);
    expect(overlay.isBusy()).toBe(false);
  });

  it('plays a burst of alerts in order without dropping or duplicating', () => {
    const played = [];
    for (const name of ['a', 'b', 'c']) {
      socket.receive(alertFrame({ headline: name }));
    }
    played.push(headline.textContent);
    expect(overlay.queue.length).toBe(2);

    vi.advanceTimersByTime(SHOW_MS + HIDE_MS);
    played.push(headline.textContent);
    vi.advanceTimersByTime(SHOW_MS + HIDE_MS);
    played.push(headline.textContent);

    expect(played).toEqual(['a', 'b', 'c']);
    expect(overlay.queue.length).toBe(0);
  });

  it('queues an alert arriving mid-display and plays it afterwards', () => {
    socket.receive(alertFrame({ headline: 'first' }));
    vi.advanceTimersByTime(3000);
    socket.receive(alertFrame({ headline: 'second' }));
    expect(headline.textContent).toBe('first');
    expect(overlay.queue.length).toBe(1);

    vi.advanceTimersByTime(SHOW_MS - 3000 + HIDE_MS);
    expect(headline.textContent).toBe('second');
    expect(box.classList.contains('show')).toBe(true);
  });

  it('uses the alert kind as the box css class', () => {
    socket.receive(alertFrame({ kind: 'pix_donation' }));
    expect(box.className).toBe('pix_donation show');
  });

  it('renders empty detail when the server sends null', () => {
    socket.receive(alertFrame({ detail: null }));
    expect(detail.textContent).toBe('');
  });

  it('treats payload content as text, not markup', () => {
    socket.receive(alertFrame({ headline: '<img src=x onerror=alert(1)>' }));
    expect(headline.textContent).toBe('<img src=x onerror=alert(1)>');
    expect(headline.querySelector('img')).toBeNull();
  });
});

describe('websocket handling', () => {
  it('drops malformed frames without breaking later alerts', () => {
    expect(() => socket.receive('{not json')).not.toThrow();
    expect(overlay.queue.length).toBe(0);
    expect(overlay.isBusy()).toBe(false);

    socket.receive(alertFrame({ headline: 'still works' }));
    expect(headline.textContent).toBe('still works');
  });

  it('reconnects after the socket closes', () => {
    expect(FakeWebSocket.instances.length).toBe(1);
    socket.drop();
    expect(FakeWebSocket.instances.length).toBe(1);

    vi.advanceTimersByTime(RECONNECT_MS);
    expect(FakeWebSocket.instances.length).toBe(2);
    expect(FakeWebSocket.instances[1].url).toContain('/ws');
  });
});
