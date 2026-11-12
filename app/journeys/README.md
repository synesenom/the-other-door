# Journeys: the main paths through the whole app, and the failures you can act on

The journeys replace the manual "try it with real data" pass after a UI change. Each one drives the
**built Electron app** against the **real door MCP server**, in a temp home made from realistic data,
and checks two things after every user action:

1. **The screen** — the exact words, roles and states the user sees (Playwright's role and label locators).
2. **The data** — what changed on disk (`profile/`, `jobs/applications.json`, `cv.md`…) and what did not.

```bash
npm run test:journeys                      # build, then every journey
npm run test:journeys -- matches           # one file
npm run test:journeys:core                 # the main paths only (tests tagged @core): what CI runs
npm run test:journeys:coverage             # the same with renderer coverage: journeys-coverage/report.md
```

On macOS, a sandboxed shell cannot start Electron (its Mach ports are refused): run these from a normal terminal.

## The world (`test/world/`)

Everything is door's own code except the edges that would leave the computer. Those answer from a
**world** that the test builds (`buildWorld(options)` in `test/world/build.ts`):

| Edge | Stand-in | How a test breaks it |
|---|---|---|
| The network | `boot.py`: every non-local socket refused; `requests` answers from `world.json`'s `internet` | an URL that is not in `internet` is offline |
| Job boards (`search`) | `boot.py`: one module per board, returning the world's `fresh` ads | `boards.<site>.fail` in world.json (the board records an error) |
| Employer feeds (`follow`, `collect`) | `boot.py`: `feeds` (company → platform, entry, postings) | — |
| `claude` | `claude.py`, first on PATH: sign-in, then every `-p` call by its system prompt (scores, titles, CV draft, keywords, enrich, gaps, revise, the tailor…) | `world.faults({ claude: { tailor: { fail: '…' } } })`, `delay_s`, `answer` |
| LaTeX | `tectonic.py`: real PDFs (pypdfium2), page count follows the text | a `.tex` containing `\worldfail` |
| Google Drive | `boot.py`: a folder in the world plays the account; door's real sync logic runs over it | `world.faults({ drive: { upload: 'quota exceeded' } })` |
| Phone tunnel | `boot.py`: a pretend tunnel | `world.faults({ phone: { start: { error: '…' } } })` |
| Any tool | `boot.py` wraps every MCP tool | `world.faults({ tools: { show: { error: '…', once: true } } })`, `delay_s`, `crash` (the server dies) |
| The OS (dialogs, links, folders) | `fixtures.ts` replaces `dialog` and `shell` in the main process | `os.nextOpen([path])`, `os.nextSave(path \| null)`, `os.opened()` |
| The clock | the server's (`boot.py`) and the window's (`page.clock`) both start at `NOW` (2026-10-26 09:00 UTC) | — |

Faults are read again before every call, so a test breaks a thing at the moment it wants and clears it
(`world.clearFaults()`) to check the app recovers. `world.calls()` / `toolCalls(name)` / `claudeCalls(kind)`
say what the app asked for (e.g. "no model call before Save").

The data (`test/world/data/`) is fiction written to look real: four people (`mette`, a senior data
scientist in Copenhagen with a full history; `lea`, a management controller in Lyon with a French CV;
`bence`, a backend engineer in Budapest; `jonas`, a new graduate in Aarhus whose CV has gaps) and 37
full job ads in English, Danish, French and Hungarian. Mette's world has a job in every column of
the Applications board (`FULL_LEDGER`), prepared and sent materials compiled through door's own compile,
three ads a job board returns on the next run, and a past run.

## Writing a journey

A journey covers a main path end to end, or a failure the user can act on (docs/design/README.md, principle 8): one test each. Rare branches, odd answer shapes, timeouts and wording variants go to a unit test (`src/**/*.test.ts(x)`, or the Python suite for what the server decides), and a narrow-window or "stays silent" check is kept once per area. A journey on a main path that should run in CI gets `{ tag: '@core' }`; `npm run test:journeys:core` runs those, as `.github/workflows/app.yml` does on Linux.

- One test per path or failure, named for what the user does and sees.
- The checklist is `inventory/<area>.md`: every action and branch the screens have, with the exact
  words. Each item is marked with the journey that covers it, the unit test that does
  (`— unit: <file>`), or why it is not a journey.
- Find things as the user does: `getByRole(role, { name, exact: true })`, `getByLabel`. No CSS classes,
  no test ids.
- After each action: the screen, then the disk (`world.readJson('jobs/applications.json')`), then, where
  it matters, that nothing else happened (`world.toolCalls('save_cv')` is empty).
- When the app does the wrong thing, the test still says what is right and is marked
  `test.fail(true, 'BUG: …')`: the suite stays green, and the day the bug is fixed the test says so.

## Coverage

`npm run test:journeys:coverage` records the renderer's V8 block coverage in every test and attributes
it to source files (the renderer bundle is unminified, one marker per module). `journeys-coverage/report.md`
lists, per file, the share of code the journeys ran and every block none of them reached. A block no
journey can reach is either dead code or a missing journey.

## What the journeys do not replace

The real `claude` (whether a tailored CV is good), the live job sites (the Python live smoke tests),
Google's and Claude's real sign-in pages, the native dialogs and notifications of the OS, dragging a file
from Finder, and the packaged app (`npm run test:package`). Before a release: one real sign-in, one real
run and one real Prepare.
