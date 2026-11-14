// The phone tab bar's icons (docs/design: a 22 px stroke icon over each label); hidden from assistive
// tech, which reads the label. Drawn in currentColor, so they follow the tab's ink.
const PATHS: Record<string, string> = {
  Matches: 'M4 6h16M4 12h16M4 18h10',
  Applications: 'M4 8h16v11H4zM9 8V5h6v3',
  Profile: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 20c1.5-4 4.5-6 8-6s6.5 2 8 6',
  Analytics: 'M5 20v-7M12 20V5M19 20v-11',
  Settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1',
}

export function TabIcon({ name }: { name: string }) {
  return (
    <svg className="tab-icon" aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[name] ?? ''} />
    </svg>
  )
}
