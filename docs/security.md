# Security and privacy

What *The other door* does with your CV and your job hunt, what leaves your computer and where it goes,
and what it does not protect you from. It is a personal project, run on your own computer with your own
Claude plan. This page says only what the code does; where something is not enforced, it says so.

<!-- toc -->
**Contents**

- [Where your data lives](#where-your-data-lives)
- [What leaves your computer](#what-leaves-your-computer)
  - [Job sites](#job-sites)
  - [Claude](#claude)
  - [Google Drive](#google-drive)
  - [Wikidata](#wikidata)
- [The phone](#the-phone)
- [What Claude's output can do](#what-claudes-output-can-do)
- [What it downloads](#what-it-downloads)
- [Problem reports](#problem-reports)
- [Reporting a security problem](#reporting-a-security-problem)
- [What it does not protect against](#what-it-does-not-protect-against)
<!-- /toc -->

## Where your data lives

Everything is on your own computer, in the data folder: `profile/` (your settings, CV, story bank) and
`jobs/` (postings, your applications, the CVs and letters it made), plus `backups/` and `logs/`. By default
that is the checkout; the desktop app and `DOOR_HOME` put it in a folder of your choice
([Your data](data.md)). The project runs no server and holds no account of yours.

The files are ordinary files of your user account. *The other door* does not encrypt them: whoever can
read your folder can read them. The folder's contents are never committed to the repository.

## What leaves your computer

Nothing is sent to the project. What goes out goes to job sites, Claude, Google Drive and Wikidata (below),
to Cloudflare when you set up the phone ([The phone](#the-phone)), and to GitHub and Google for downloads
and update checks ([What it downloads](#what-it-downloads)).

### Job sites

It reads job boards, employers' job feeds and career pages. Every request is logged out: no login, no
cookies of yours, no CAPTCHA solving. No request
carries your CV; a search sends your search terms (and your city or country for a board that needs one),
and a followed employer's page is asked for by its address. Requests to one site are paced, one at a time per
site, and a site's `Crawl-delay` is honoured. The sources that only find employers (LinkedIn,
profession.hu, HelloWork, Jobbsafari) are off until you turn them on, and stop at the first sign of
pushback (LinkedIn waits out one refusal, then stops for the run).

Two things to know. The requests send a common browser's `User-Agent` and do not name the project.
And `robots.txt` is read for its `Sitemap:` lines and `Crawl-delay` but does not block a request; the
bar for each source is its terms, recorded as a verdict ([how it fetches](job-sites.md#how-the-other-door-fetches),
[the legal disclaimer](../LEGAL_DISCLAIMER.md)).

Every request to a job site, and every redirect of it, connects only to a public internet address,
and ignores the system proxy and `.netrc`. A link that points at
your computer, your home network or a cloud metadata address is refused. This matters because a posting
or a page you import can contain any link.

### Claude

Every model call goes through your own `claude` command line tool, on your own Claude plan (`claude -p`).
There is no API key anywhere. What the call sends is read by Anthropic under your account and its terms:

- **Scoring:** each posting, with your whole CV and some of your settings (role targets, location, languages,
  minimum score, preferences). The call is given no tools.
- **Preparing and revising an application:** your CV, story bank, the posting, your name and email, and
  what it writes.
- **Other short calls:** reading your CV when you set up, proposing search terms and titles, grouping skill
  names, checking the facts of a CV and letter, answering "ask about your jobs". The salary estimate, which uses
  web search, gets the ad's own lines and your years of experience as a number, no line of your CV. Finding an employer's careers page searches the web for the employer's name.

Every call names its MCP servers explicitly (`--strict-mcp-config`), so your other MCP servers are not
loaded into it. If you drive *The other door* from a Claude Code conversation, what a tool returns is read
by that conversation. Which plan pays is `claude_config_dir`. How much a call costs is logged in
`jobs/usage.jsonl`, on this computer only; it is left out of exports and of Google Drive.

In a Claude Code conversation Claude never reads an ad's text. An ad is written by a stranger and a conversation can run commands on your computer, so a line in the ad asking the model to ignore the text is only a request. `show` there opens the full ad in your browser (its own address, or a saved plain page under `.view/` with the text escaped) and hands Claude a short summary that one tool-less Haiku call extracts and code cuts to fixed bounds; no tool answer carries a description. Every text in a tool's answer is cut and comes in a marker `<ad-…>…</ad-…>` with a token chosen anew for each answer (titles, companies, errors, warnings, notes of a prepared CV, employer names, progress lines, whatever the route an ad's words took into it), except the ids, paths, statuses and timestamps the code makes itself; `ask`'s answer is capped and wrapped the same way. `show` opens an ad once for each job while the server runs. The desktop app, the phone and the command line are not conversations and show the whole ad.

A posting is written by someone else. A gate cleans it before a model reads it and every prompt says to treat
it as data ([the ad is untrusted input](how-it-works.md#the-ad-is-untrusted-input), which also lists what the
gate does not catch). Where the model has tools, they are cut down; see [What Claude's output can do](#what-claudes-output-can-do).

### Google Drive

Optional, off until you connect it. It stores one archive, `My Drive/The other door/door-data.tar.gz`, of
your `profile/` and `jobs/` (not this computer's usage log, not `claude_config_dir`). The archive is not
encrypted: it is as private as your Google account. The app asks Google for the `drive.file` permission only,
so it can see just the folder and file it made, nothing else in your Drive. The connection is kept in your
user config folder, readable by you only, outside the data folder so it never travels with an export
([Your data](data.md)). "Disconnect" in
Settings removes the connection. See also the [privacy page](https://enysmones.com/the-other-door/#privacy).

### Wikidata

To find an employer's own website from its name, *The other door* asks Wikidata's public API
(no key, no login) for the employer's name, at most 60 names a run. Only employer names are sent.

## The phone

The phone app is the desktop app's screens in a browser. The computer does all the work and holds all the
data; the phone holds none of its own.

**How it is served.** The server listens on this computer only (`127.0.0.1`, unless you pass `--host`).
For your phone to reach it, the app (or Claude Code's `phone_start`) starts a Cloudflare quick tunnel: an
`https://<random>.trycloudflare.com` address, new each time, with no router port opened. Cloudflare's servers
see the traffic decrypted on its way through, and the new address is looked up once through Cloudflare's
public DNS before it is shown. On a Mac the computer is kept awake while it serves (`caffeinate`).
Stopping it, or the tunnel dying, ends the pairing too, and a phone needs to be paired again.

**Pairing.** The app's QR code holds a one-time code of 24 random characters that works for five
minutes; it sits in the part of the link after `#`, which a browser does not send to a server. A code from
`./door serve pair` is 8 characters and works for ten minutes. One phone is paired at a time. The server
keeps only hashes of codes and tokens, in a folder only you can open, so a stolen file pairs nothing, and
repeated wrong codes from one address lock it out for a while. Disconnecting makes the phone's token stop
working at once.

**What a paired phone can do.** Not what a Claude Code session on your computer can. The server answers only
the eleven tools the phone app uses, with the arguments the app sends and no others, and strings over a cap
are refused. It never takes a local file path, and it refuses `ask`, free-text `revise`, profile edits, Drive,
export and import. What it answers has this computer's folders masked, no Drive account, and only the profile
settings the phone shows, and a day allows only so many prepares, imports and runs ([On your phone](manual-app.md#on-your-phone)).
The files it can fetch are a job's rendered CV and letter (PDF and page images) and nothing else of the job's
folder, and the page runs only its own scripts.

What it cannot promise: the page and the manifest are public, so anyone who finds the tunnel address sees
the app's code (no data); every route that reaches data needs the token.

## What Claude's output can do

A model reads untrusted text (postings, web pages) and writes your CV and letter. So the output is
treated as untrusted too:

- **The body is an allow-list.** `cv.html` and `cover_letter.html` hold only a small set of tags, classes
  and links (`https:`, `mailto:` and in-page ones). No script, style, image, SVG, `on*` handler or other
  link. `compile` refuses a body with anything else.
- **The printer is sealed.** The PDF is printed by a headless Chromium with JavaScript off, a fresh
  profile, a loopback server over the job's folder only, and every other request failed (other hosts,
  `file:`, `data:`, `blob:`). One limit: on Linux as root, or where the system refuses it, Chromium's own
  sandbox is turned off; the rest still holds.
- **The tailor has no shell.** It runs from the job's output folder in `claude -p --restricted`. It can
  read only copies of your CV, story bank and templates, the posting (without its score) and that folder,
  none of your other settings, write only there, and call `compile` and `check_facts`. It
  cannot write your story bank or `cv.md`. Other calls that read an ad get no tools or web search
  alone; reading your public pages (setting up, Add a page) may fetch up to 20 pages it chooses.
- **Facts are checked, not blocked.** Numbers, years, employers, skills, certifications and degrees in a
  CV or letter that your CV and story bank do not back are listed (`check_facts`), and you are told. It is
  a check by another model call, not a guarantee, and it does not stop you sending.
- **A tool's local path stays inside your data folder.** Tools that take a path (reading a CV file, a
  photo, an export or import) refuse one outside the data folder and the checkout. An import also refuses
  links, absolute paths and `..` in the archive. In the desktop app every path comes from a dialog the main
  process opens: the window cannot name one.
- **The desktop window is walled in.** Context isolation and the sandbox are on, Node is off in the page,
  every permission request is denied, it can navigate only to its own page, and only `http(s)` links open in
  your browser. A test fails if anything under `app/` runs the CLI or a model.

## What it downloads

Two programs are downloaded, each from a pinned version and checked against a sha256 written in the code
before it is used: the Chromium headless shell that prints PDFs (from Google's Chrome for Testing), and
`cloudflared` for the phone (from Cloudflare's GitHub releases). The installed app brings Chromium with it.
The fonts are shipped with the code. `./door doctor --fix` installs Claude's `claude` tool with Claude's own
installer (`claude.ai/install.sh`, or npm), which is not pinned.

**App updates** come from this project's GitHub releases. The check sends the app's version and nothing else of yours.

## Problem reports

`logs/door.log` holds one line per failure: a tool's name and its error message. It is not given your CV,
profile or ads, but an error message can repeat words you gave a tool (a job named by words that matched
nothing). `./door data report`, or Settings → Help → Save logs…, packs it with the last run records and checks
into one `.zip`, emails and folders masked, nothing from `profile/` and no postings
([the problem log](data.md#the-problem-log)). It is saved only where you choose and never sent: you attach it yourself.

## Reporting a security problem

See [SECURITY.md](../SECURITY.md): please do not put the details in a public issue.

## What it does not protect against

- **Someone with your computer or your account.** Your data folder and `drive.json` are readable by your
  user, and nothing is encrypted. Disk encryption and a screen lock are your protection.
- **Cloudflare, the sites, Anthropic and Google.** What goes to them (above) is under their own terms and
  retention. If Cloudflare reading the phone's traffic is not acceptable, do not set up the phone.
- **A job ad that tricks a model.** The gate, the scorer's own quoting of text aimed at it (removed, then the ad scored again) and the cut-down tools limit what a hostile ad can do, but a
  model can still be misled into a wrong score or a wrong sentence in a letter. Read what you send.
