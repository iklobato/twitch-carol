import type { ReactNode } from 'react'

import { t, type MessageKey } from '../i18n'
import type { Route } from '../router'

type NavKey = 'home' | 'channel' | 'money' | 'audience' | 'settings'

type NavItem = { key: NavKey; href: string; label: MessageKey; icon: ReactNode }

const ICON_PROPS = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  className: 'h-[18px] w-[18px] shrink-0',
  'aria-hidden': true,
} as const

// ponytail: "My channel" stays until its blocks move to Money, Audience and Lives.
const NAV_ITEMS: NavItem[] = [
  {
    key: 'home',
    href: '#/',
    label: 'app.nav.home',
    icon: (
      <svg {...ICON_PROPS}>
        <path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />
      </svg>
    ),
  },
  {
    key: 'channel',
    href: '#/channel',
    label: 'app.nav.channel',
    icon: (
      <svg {...ICON_PROPS}>
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="M10 9l5 3-5 3z" />
      </svg>
    ),
  },
  {
    key: 'money',
    href: '#/money',
    label: 'app.nav.money',
    icon: (
      <svg {...ICON_PROPS}>
        <path d="M12 3v18M16 7.5c0-1.7-1.8-3-4-3s-4 1.3-4 3 1.8 2.6 4 3 4 1.4 4 3.2-1.8 3-4 3-4-1.3-4-3" />
      </svg>
    ),
  },
  {
    key: 'audience',
    href: '#/audience',
    label: 'app.nav.audience',
    icon: (
      <svg {...ICON_PROPS}>
        <circle cx="9" cy="8" r="3.5" />
        <path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5M16 4.8a3.5 3.5 0 0 1 0 6.4M18.5 14.8c1.6.8 2.6 2.5 3 5.2" />
      </svg>
    ),
  },
  {
    key: 'settings',
    href: '#/settings',
    label: 'app.nav.settings',
    icon: (
      <svg {...ICON_PROPS}>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" />
      </svg>
    ),
  },
]

/** A live report and a search result both start from the list of lives, so
 * they keep Home lit. */
const ACTIVE_FOR_VIEW: Record<Route['view'], NavKey> = {
  home: 'home',
  stream: 'home',
  search: 'home',
  channel: 'channel',
  money: 'money',
  audience: 'audience',
  settings: 'settings',
}

export default function Sidebar({ route }: { route: Route }) {
  const active = ACTIVE_FOR_VIEW[route.view]
  return (
    <nav
      aria-label={t('app.nav.label')}
      className="flex flex-wrap gap-1 border-b border-line bg-rail px-3 py-3 md:sticky md:top-0 md:h-screen md:w-56 md:shrink-0 md:flex-col md:flex-nowrap md:border-b-0 md:border-r md:py-5"
    >
      <a
        href="#/"
        className="flex w-full items-center gap-2 px-3 pb-2 font-display text-lg font-bold text-ink md:pb-4"
      >
        <span className="h-2.5 w-2.5 rounded-full bg-accent" aria-hidden="true" />
        Stream Intel
      </a>
      {NAV_ITEMS.map((item) => {
        const isActive = item.key === active
        return (
          <a
            key={item.key}
            href={item.href}
            aria-current={isActive ? 'page' : undefined}
            className={`flex min-h-11 items-center gap-2.5 rounded-lg px-3 text-sm font-medium ${
              isActive
                ? 'bg-accent-soft text-ink'
                : 'text-ink-muted hover:bg-panel-raised hover:text-ink'
            }`}
          >
            {item.icon}
            {t(item.label)}
          </a>
        )
      })}
    </nav>
  )
}
