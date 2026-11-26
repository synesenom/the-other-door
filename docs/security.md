# Security and privacy

This page is for anyone deciding whether to trust *The other door*. It says who and what the app trusts,
what each source it does not trust could try, what stops it, what the protections cost you, and what is not
covered yet. It is a personal project, run on your own computer with your own Claude plan. The page says only
what the code does; where something is not enforced, it says so. Each protection names the issue or pull
request that added it, and links to the page that holds the detail.

<!-- toc -->
**Contents**

- [Who is trusted](#who-is-trusted)
- [Where your data lives](#where-your-data-lives)
- [What leaves your computer](#what-leaves-your-computer)
- [How each untrusted source is held back](#how-each-untrusted-source-is-held-back)
  - [Job ads, scraped pages and employer feeds](#job-ads-scraped-pages-and-employer-feeds)
  - [Employer pages and discovery sources](#employer-pages-and-discovery-sources)
  - [Pages you give it to read](#pages-you-give-it-to-read)
  - [CV files you open](#cv-files-you-open)
  - [Archives you import and Drive pulls](#archives-you-import-and-drive-pulls)
  - [What a model writes](#what-a-model-writes)
  - [A Claude Code chat](#a-claude-code-chat)
  - [A paired phone](#the-phone)
  - [Releases and updates](#releases-and-updates)
- [Google Drive, Wikidata and the other services](#google-drive-wikidata-and-the-other-services)
- [What it downloads](#what-it-downloads)
- [Problem reports](#problem-reports)
- [What these protections cost you](#what-these-protections-cost-you)
- [Not yet done](#not-yet-done)
- [What is not covered](#what-is-not-covered)
- [Reporting a security problem](#reporting-a-security-problem)
<!-- /toc -->

## Who is trusted

**Trusted: you**, the person at the computer. Your CV, story bank and settings are yours, and the app does
what you tell it.

**Not trusted** is anyone else whose words or files the app reads or runs:

- the authors of job ads, and of the pages and feeds the ads come from;
- employer pages and the discovery sources (LinkedIn and others) that point to employers;
- pages you give it to read for your CV (setting up, "Add a page");
- CV files you open;
- an archive you import, or data pulled from Google Drive;
- a paired phone, and whoever holds its token;
- a Claude Code chat that reads what the tools answer;
- whoever could publish a release, or tamper with an update on its way to you.

What the attacker wants is the same each time: to change your CV or settings, to steer a Claude call that
has tools, to use up your Claude plan, to make your computer fetch something on your own network, or to carry
your CV out. The sections below say, for each source, what stops that.

## Where your data lives

Everything is on your own computer, in the data folder: `profile/` (your settings, CV, story bank) and
`jobs/` (postings, your applications, the CVs and letters it made), plus `backups/` and `logs/`. By default
that is the checkout; the desktop app and `DOOR_HOME` put it in a folder of your choice
([Your data](data.md)). The project runs no server and holds no account of yours.

The files are ordinary files of your user account. *The other door* does not encrypt them: whoever can
read your folder can read them. The folder's contents are never committed to the repository.

## What leaves your computer

Nothing is sent to the project. What goes out goes to job sites, Claude, Google Drive and Wikidata, to
Cloudflare when you set up the phone, and to GitHub and Google for downloads and update checks. Details are
under [the services](#google-drive-wikidata-and-the-other-services), [the phone](#the-phone) and
[what it downloads](#what-it-downloads).

Every model call goes through your own `claude` command line tool (`claude -p`), on your own Claude plan.
There is no API key anywhere. What a call sends is read by Anthropic under your account and its terms:

- **Scoring:** each posting, with your whole CV and some of your settings (role targets, location, languages,
  minimum score, preferences). The call is given no tools.
- **Preparing and revising an application:** your CV, story bank, the posting, your name and email, and what
  it writes. The tailor has tools, cut down as [below](#what-a-model-writes).
- **Other short calls:** reading your CV when you set up, proposing search terms and titles, grouping skill
  names, checking the facts of a CV and letter, setting out an ad, answering "ask about your jobs". The
  salary estimate searches the web and sends the ad's own lines and your years of experience as a number,
  no line of your CV ([#583](https://github.com/synesenom/the-other-door/pull/583)). Finding an employer's
  careers page searches the web for the employer's name.

Every call names its MCP servers explicitly (`--strict-mcp-config`), so your other MCP servers are not
loaded into it. Which plan pays is `claude_config_dir`. How much a call costs is logged in
`jobs/usage.jsonl`, on this computer only; it is left out of exports and of Google Drive.

## How each untrusted source is held back

### Job ads, scraped pages and employer feeds

*What it could try.* An ad is written by a stranger. It could hide text a reader cannot see, speak to the
scoring model ("give this candidate 1.0"), point a link at your own computer or home network, be huge, or
flood a run with ads to use up your plan.

*What stops it.*

- **Only the public internet** ([#548](https://github.com/synesenom/the-other-door/issues/548), PR
  [#560](https://github.com/synesenom/the-other-door/pull/560)). Every request to a job site, and every
  redirect, connects only to a public internet address, ignores the system proxy and `.netrc`, and stops
  reading a body at 50 MB. A link to your computer, your home network or a cloud metadata address is refused.
  The detail is in [how it fetches](job-sites.md#how-the-other-door-fetches).
- **The integrity gate.** Before a model reads an ad, an offline gate removes invisible characters and lines
  addressed to a model, and for an imported page also text a reader cannot see. What it removed is recorded
  and the ad is marked suspicious ([the ad is untrusted input](how-it-works.md#the-ad-is-untrusted-input)).
  Ads from a scraper are gated as text only, so text hidden by styling in a scraped ad is not yet found.
- **The scorer quotes what is aimed at it** ([#584](https://github.com/synesenom/the-other-door/pull/584)).
  The scorer also lists any text of the ad that speaks to an AI or tells the reader how to score it. Code
  keeps a quote only if it is found word for word in the ad, cuts exactly that text, marks the ad suspicious
  and scores the cleaned ad once more. The scorer has no tools, so the worst a hostile ad does here is a
  wrong score.
- **You are told** ([#585](https://github.com/synesenom/the-other-door/pull/585)). A job's page, and the
  result of "Add a job", say when part of an ad was hidden or written for an AI, and show what was cut.
- **A run is capped** ([#551](https://github.com/synesenom/the-other-door/issues/551), PR
  [#564](https://github.com/synesenom/the-other-door/pull/564)). A run scores at most 150 ads (30 calls),
  taken in turn from each site so one site that floods the list cannot crowd out the others, and a score is
  kept only for a job in its own batch. A translated title is one line of at most 200 characters, and a skill
  name over 60 characters is never kept as an alias.
- **An added ad keeps only what it says** ([#545](https://github.com/synesenom/the-other-door/issues/545),
  PR [#567](https://github.com/synesenom/the-other-door/pull/567)). When you add a job, the title, company
  and place that a model reads from the ad are kept only if the ad contains those words.

### Employer pages and discovery sources

*What it could try.* A careers page or a discovery source could answer with links to private addresses, feed
back a model-readable instruction, or push back until the app misbehaves.

*What stops it.* The same public-only connection as the boards
([#580](https://github.com/synesenom/the-other-door/pull/580)). The sources that only find employers
(LinkedIn, profession.hu, HelloWork, Jobbsafari) are off until you turn them on, logged out only (no login,
cookies or session), paced, capped, stopped for the run at the first sign of pushback and rested for a day
after a refusal. Every source has a recorded verdict on its terms, and one the terms forbid runs only after
you turned it on and read the disclaimer; one that is reserved is never fetched
([how it fetches](job-sites.md#how-the-other-door-fetches), [the legal disclaimer](../LEGAL_DISCLAIMER.md)).
Asking a careers-page model about employers is capped at 30 a run (#551). `robots.txt` is read for its
`Sitemap:` lines and `Crawl-delay` but does not block a request, and the requests send a common browser's
`User-Agent`; the bar for each source is its terms.

### Pages you give it to read

*What it could try.* A page you give to "Add a page" or setting up could carry instructions to the model, to
make it send your CV somewhere or read your files.

*What stops it* ([#549](https://github.com/synesenom/the-other-door/issues/549), PR
[#561](https://github.com/synesenom/the-other-door/pull/561)). Reading pages and writing your CV are two
separate calls. The call that reads the pages is given only their addresses and one tool, which fetches at
most 20 pages, only public addresses, never LinkedIn or Indeed (their terms forbid it), and cuts each page
to a size. The call that sees your CV has no tools at all and gets the page text as data. So no call that
sees your private data has the network, and no call with the network sees your private data. The limits are
in code, not in the prompt ([architecture](architecture.md), the `cv enrich` row).
Text from a page, an ad or a model is escaped before the command line prints it, so it cannot use terminal
markup.

### CV files you open

*What it could try.* A settings file or CV could name a file outside your profile, or be built to fill
memory.

*What stops it* ([#552](https://github.com/synesenom/the-other-door/issues/552), PR
[#566](https://github.com/synesenom/the-other-door/pull/566)). The CV, the templates and the photo named in
`config.json` must be files inside the profile folder, whatever way the settings arrive (typed, imported or
pulled from Drive). A CV file is read only up to a size: a part of a DOCX of 20 MB unpacked, a PDF of 30
pages and 300,000 characters. A tool that takes a path (reading a CV file, a photo, an export or import)
refuses one outside the data folder and the checkout; in the desktop app every path comes from a dialog the
main process opens, so the window cannot name one.

### Archives you import and Drive pulls

*What it could try.* An archive could carry links or paths that write outside the data folder, or a settings
file with paths of its own.

*What stops it.* An import refuses links, absolute paths and `..` in the archive, and the settings it holds
go through the same check as a typed one (above). A Drive pull is the same archive. Drive is optional and
sees only its own folder ([below](#google-drive-wikidata-and-the-other-services)). Archives have no size
limit ([not covered](#what-is-not-covered)).

### What a model writes

*What it could try.* A model reads untrusted text and writes your CV and letter. An ad could steer it to
write something into the PDF, to carry your data in a link, to change your story bank, or to run a command.

*What stops it.*

- **The tailor sees only what it needs**
  ([#582](https://github.com/synesenom/the-other-door/pull/582)). It runs from a folder of its own, in
  `claude -p --restricted` (no shell). It reads only copies of your CV, story bank and templates, the posting
  without its score, and your name and email as text. It never sees `config.json`, your employer list or
  the rest of your profile, and the copies are removed when it ends.
- **It writes no stories and no links of its own**
  ([#550](https://github.com/synesenom/the-other-door/issues/550), PR
  [#562](https://github.com/synesenom/the-other-door/pull/562)). A prepared job adds nothing to your story
  bank, and a link in a CV or letter that your CV and story bank do not write prints as plain text, so a link
  cannot carry what the model read to a stranger.
- **The body is an allow-list.** `cv.html` and `cover_letter.html` hold only a small set of tags, classes
  and links (`https:`, `mailto:` and in-page ones). No script, style, image, SVG or `on*` handler. `compile`
  refuses a body with anything else.
- **The printer is sealed.** The PDF is printed by a headless Chromium with JavaScript off, a fresh profile, a
  loopback server over the job's folder only, and every other request failed. On Linux as root, or where the
  system refuses it, Chromium's own sandbox is turned off; the rest still holds.
- **Facts are checked, not blocked.** Numbers, years, employers, skills, certifications and degrees that
  your CV and story bank do not back are listed (`check_facts`) and you are told. It is a check by another
  model call, not a guarantee, and it does not stop you sending.
- **Scraper repair is gone** ([#553](https://github.com/synesenom/the-other-door/issues/553), PR
  [#565](https://github.com/synesenom/the-other-door/pull/565)). No model writes code from a site's page.
  A site that changes is fixed in a new version of the app.
- **The desktop window is walled in.** Context isolation and the sandbox are on, Node is off in the page,
  every permission request is denied, it can navigate only to its own page, and only `http(s)` links open in
  your browser. A test fails if anything under `app/` runs the CLI or a model.

### A Claude Code chat

*What it could try.* A chat can run commands on your computer. If a tool answer carried an ad's text, a line
in the ad could tell the chat to use that power.

*What stops it* ([#586](https://github.com/synesenom/the-other-door/pull/586)). In a chat, no tool answer
carries an ad's text. `show` opens the full ad in your browser (its own address, or a saved plain page with
the text escaped) and gives Claude only a short summary, which one tool-less call extracts and code cuts to
fixed bounds. Every other text in an answer (titles, companies, errors, notes, employer names, progress
lines) is cut and comes inside a marker `<ad-…>…</ad-…>` with a random token chosen anew for each answer, so
text inside it cannot close it early or pass for the server's own words. Only the values the code makes
itself (ids, paths, statuses, timestamps) stay as they are, and tools that return only your own data (your
CV, story bank, profile, checks of this computer) answer whole. The desktop app, the phone and the command
line are not chats and show the whole ad. A Claude that The other door itself starts in the background is
never taken for the app, so its answers are guarded too; the one exception is the tailor's own server, which
names its reader, because the tailor reads the posting itself.

### The phone

The phone app is the desktop app's screens in a browser. The computer does all the work and holds all the
data; the phone holds none of its own. *What it could try:* a stolen phone, a leaked token or a hostile page
in its browser.

**How it is served.** The server listens on this computer only (`127.0.0.1`, unless you pass `--host`). For
your phone to reach it, the app starts a Cloudflare quick tunnel: an `https://<random>.trycloudflare.com`
address, new each time, with no router port opened. Cloudflare's servers see the traffic decrypted on its way
through. Stopping it, or the tunnel dying, ends the pairing too.

**Pairing.** The app's QR code holds a one-time code of 24 random characters that works for five minutes; it
sits after the `#` of the link, which a browser does not send to a server. One phone is paired at a time. The
server keeps only hashes of codes and tokens, in a folder only you can open, and repeated wrong codes from
one address lock it out for a while. Disconnecting makes the token stop working at once.

**What a paired phone can do** ([#544](https://github.com/synesenom/the-other-door/issues/544), PR
[#568](https://github.com/synesenom/the-other-door/pull/568)). Not what a Claude Code session on your
computer can. The server answers only the eleven tools the phone app uses, with the arguments the app sends
and no others. It never takes a local file path, and it refuses `ask`, `revise`, profile edits, Drive, export
and import. A string over a cap (30,000 characters for a pasted ad, 2,000 for a note or a link, 300 for any
other) and a request body over about 1 MB are refused. A day allows 10 prepares, 30 imported ads and 6
runs ([On your phone](manual-app.md#on-your-phone)).

**What it is sent** ([#546](https://github.com/synesenom/the-other-door/issues/546), PR
[#569](https://github.com/synesenom/the-other-door/pull/569)). Every answer and error has this computer's
folders masked, the Drive account left out, and only the profile settings the phone shows. The phone can
fetch a job's rendered CV and letter (PDF and page images) and nothing else of the job's folder, and the page
runs only its own scripts. An ad you import from the phone has its title and company kept only if the ad
contains those words ([#545](https://github.com/synesenom/the-other-door/issues/545), above).

What it cannot promise: the page and the manifest are public, so anyone who finds the tunnel address sees
the app's code (no data); every route that reaches data needs the token. One free-text channel remains
on purpose: someone holding the phone can paste an ad written to steer the tailor and prepare it. That is
bounded by the daily limits, the tailor's walls and the allow-list above, and closing it would remove what
the phone is for.

### Releases and updates

*What it could try.* Whoever could write to a release could ship code that installed apps run. See
[not yet done](#not-yet-done): this protection is not in place yet.

## Google Drive, Wikidata and the other services

**Google Drive** is optional, off until you connect it. It stores one archive,
`My Drive/The other door/door-data.tar.gz`, of your `profile/` and `jobs/` (not this computer's usage log, not
`claude_config_dir`). The archive is not encrypted: it is as private as your Google account. The app asks
Google for the `drive.file` permission only, so it can see just the folder and file it made, nothing else in
your Drive. The connection is kept in your user config folder, readable by you only, outside the data folder
so it never travels with an export ([Your data](data.md)). "Disconnect" in Settings removes the connection.
See also the [privacy page](https://enysmones.com/the-other-door/#privacy).

**Wikidata.** To find an employer's own website from its name, the app asks Wikidata's public API (no key, no
login) for the employer's name, at most 60 names a run. Only employer names are sent.

**Cloudflare** carries the phone's traffic ([the phone](#the-phone)); **GitHub** serves releases and update
checks, which send the app's version and nothing else of yours.

## What it downloads

Two programs are downloaded, each from a pinned version and checked against a sha256 written in the code
before it is used: the Chromium headless shell that prints PDFs (from Google's Chrome for Testing), and
`cloudflared` for the phone (from Cloudflare's GitHub releases). The installed app brings Chromium with it.
The fonts are shipped with the code. `./door doctor --fix` installs Claude's `claude` tool with Claude's own
installer (`claude.ai/install.sh`, or npm), which is not pinned.

## Problem reports

`logs/door.log` holds one line per failure: a tool's name and its error message. It is not given your CV,
profile or ads, but an error message can repeat words you gave a tool. `./door data report`, or Settings →
Help → Save logs…, packs it with the last run records and checks into one `.zip`, emails and folders masked,
nothing from `profile/` and no postings ([the problem log](data.md#the-problem-log)). It is saved only where
you choose and never sent: you attach it yourself.

## What these protections cost you

Each limit has a reason above. Here they are in one place.

- **In a Claude Code chat the ad opens in your browser, and Claude sees only a summary.** So an ad cannot
  steer a chat that can run commands. The first look at an older job costs one small model call; later looks
  reuse it. The app and the command line show the whole ad.
- **The tailor sees only your CV, story bank and templates.** So a letter cannot draw on your other settings,
  and an ad cannot make it copy them out.
- **The salary estimate uses your years of experience, not what is special in your history.** So the web
  search sees no line of your CV. There is no skill-gap report any more.
- **A suspicious ad has text cut out and is scored twice.** That is one more call for such an ad.
- **Fetching:** no private networks, no proxy, nothing over 50 MB. When it reads your own pages it fetches
  at most 20, and no LinkedIn or Indeed pages.
- **A run scores at most 150 ads and asks a model about at most 30 employers.** The rest wait for the next
  run.
- **A broken site waits for an app update.** There is no automatic repair.
- **The phone has daily limits** (10 prepares, 30 imported ads, 6 runs), **cannot revise a CV or letter, and
  cannot edit your CV or profile.** It reaches the computer over a Cloudflare quick tunnel, so Cloudflare
  sees its traffic, and after the app stops or restarts the phone needs pairing again.

## Not yet done

**Signed updates** ([epic #554](https://github.com/synesenom/the-other-door/issues/554); sub-issues
[#555](https://github.com/synesenom/the-other-door/issues/555),
[#556](https://github.com/synesenom/the-other-door/issues/556),
[#557](https://github.com/synesenom/the-other-door/issues/557),
[#558](https://github.com/synesenom/the-other-door/issues/558) are open).

Today an installed app's automatic update is not checked against a signature. The app checks the download
against a checksum that sits in the same release, and anyone who can write to a release can change both. So
whoever could publish or alter a release could ship code to installed Windows apps and Linux AppImages,
which update by themselves, at their next daily check. The builds are also not signed by Apple or
Microsoft.

What you can do meanwhile: a macOS build and the `.deb` do not update by themselves; Settings shows "Version
X is available" with a link, and you install it yourself. Install only from this project's releases page.

## What is not covered

- **Someone with your computer or your account.** Your data folder and the Drive connection are readable by
  your user, and nothing is encrypted. Disk encryption and a screen lock are your protection.
- **Cloudflare, the sites, Anthropic and Google.** What goes to them is under their own terms and retention.
  If Cloudflare reading the phone's traffic is not acceptable, do not set up the phone.
- **A job ad that tricks a model.** The gate, the scorer's quoting, the cut-down tools and your own reading
  limit what a hostile ad can do, but a model can still be misled into a wrong score or a wrong sentence in a
  letter. Read what you send. The gate's phrase list is not replaced by a model, and styling-hidden text in
  a scraped ad is not yet found.
- **Proxies.** There is no proxy support, so a fetch never goes through one.
- **Archive size.** An archive you import has no size limit.
- **Old installs.** The planned signature check cannot protect an app of version 0.4.0 or older: it installs
  the next release unchecked once ([not yet done](#not-yet-done)).
- **Hand-downloaded installers** are not signed or checksummed by the project.
- **The phone's free-text channel**, as described under [the phone](#the-phone).

## Reporting a security problem

See [SECURITY.md](../SECURITY.md): please do not put the details in a public issue.
