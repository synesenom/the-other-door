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

Four things, to four different parties. Nothing is sent to the project.

### Job sites

It reads job boards, employers' job feeds and career pages. Every request is logged out: no login, no
cookies of yours, no CAPTCHA solving, no proxy; the system proxy and `.netrc` are not read. No request
carries your CV; a search sends your search terms (and your city or country for a board that needs one),
and a followed employer's page is asked for by its address. Requests to one site are paced, one at a time per
site, and a site's `Crawl-delay` is honoured. The sources that only find employers (LinkedIn,
profession.hu, HelloWork, Jobbsafari) are off until you turn them on, and stop at the first sign of
pushback.

Two things to know. The requests send a common browser's `User-Agent` and do not name the project.
And `robots.txt` is read for its `Sitemap:` lines and `Crawl-delay` but does not block a request; the
bar for each source is its terms, recorded as a verdict ([how it fetches](job-sites.md#how-the-other-door-fetches),
[the legal disclaimer](../LEGAL_DISCLAIMER.md)).

A request, and every redirect of it, connects only to a public internet address. A link that points at
your computer, your home network or a cloud metadata address is refused. This matters because a posting
or a page you import can contain any link.

### Claude

Every model call goes through your own `claude` command line tool, on your own Claude plan (`claude -p`).
There is no API key anywhere. What the call sends is read by Anthropic under your account and its terms:

- **Scoring:** each posting, with your whole CV and some of your settings (role targets, location, languages,
  minimum score, preferences). The call is given no tools.
- **Preparing and revising an application:** your CV, story bank, the posting and the profile files the
  tailor reads, and what it writes.
- **Other short calls:** reading your CV when you set up, proposing search terms and titles, grouping skill
  names, checking the facts of a CV and letter, answering "ask about your jobs". The skill-gap report and the
  salary estimate send the work sections of your CV with your name, email, phone and contact details taken
  out, and use Claude's web search. Finding an employer's careers page searches the web for the employer's name.

Every call names its MCP servers explicitly (`--strict-mcp-config`), so your other MCP servers are not
loaded into it. If you drive *The other door* from a Claude Code conversation, what a tool returns is read
by that conversation. Which plan pays is `claude_config_dir`. How much a call costs is logged in
`jobs/usage.jsonl`, on this computer only; it is left out of exports and of Google Drive.

A posting is written by someone else. A gate cleans it before a model reads it and every prompt says to treat
it as data ([the ad is untrusted input](how-it-works.md#the-ad-is-untrusted-input), which also lists what the
gate does not catch). Where the model has tools, they are cut down; see [What Claude's output can do](#what-claudes-output-can-do).

### Google Drive

Optional, off until you connect it. It stores one archive, `My Drive/The other door/door-data.tar.gz`, of
your `profile/` and `jobs/` (not this computer's usage log, not `claude_config_dir`). The archive is not
encrypted: it is as private as your Google account. The app asks Google for the `drive.file` permission only,
so it can see just the folder and file it made, nothing else in your Drive. The sign-in is a loopback
redirect with PKCE. The connection (a refresh token, the Google account, the archive's id) is kept in
`drive.json` in your user config folder (`~/.config/door/`, `%APPDATA%\door\` on Windows), readable by you
only (file mode 0600, folder 0700), outside the data folder so it never travels with an export. The OAuth
client id and secret are in the source: Google treats a desktop-app secret as public. "Disconnect" in
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
see the traffic decrypted on its way through. On a Mac the computer is kept awake while it serves (`caffeinate`).
Stopping it, or the tunnel dying, ends the pairing too, and a phone needs to be paired again.

**Pairing.** The QR code holds a one-time code of 24 random characters that works for five minutes and
once; it sits in the part of the link after `#`, which a browser does not send to a server. A code you
type, from `./door serve pair`, is 8 characters and works for ten minutes. A new QR code cancels every
older code. One phone is paired at a time. The phone trades the code for a device token, and the server keeps
only SHA-256 hashes of codes and tokens, in a folder only you can open (`<data folder>/.serve/`, mode 0700,
files 0600), so a stolen file pairs nothing. Ten wrong tokens or codes from one address within ten minutes lock
that address out for fifteen. Unpairing (Settings → Connections → Your phone, or `./door serve unpair`)
makes the token stop working at once.

**What a paired phone can do.** Not what a Claude Code session on your computer can. The server answers only
the eleven tools the phone app uses, with the arguments the app sends and no others, and strings over a cap
are refused. It never takes a local file path, and it refuses `ask`, free-text `revise`, profile edits, Drive,
export and import. What it answers has this computer's folders masked, no Drive account, and only the profile
settings the phone shows. A day allows 10 prepares, 30 imported ads and 6 runs to find jobs. The files it can
fetch are a job's rendered CV and letter (PDF and page images) and nothing else of the job's folder; a
page image loads through an HttpOnly, same-site cookie limited to `/files`. Answers are marked
`no-store`, and the web page itself comes with a strict content policy (its own scripts only).

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
  read the profile, the posting and that folder, write only there, and call `compile` and `check_facts`. It
  cannot write your story bank or `cv.md`. Other calls that read a page or an ad get no tools, or web
  search alone.
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
`cloudflared` for the phone (from Cloudflare's GitHub releases). A file that does not match is discarded,
and the install is staged, never half done. The installed app brings Chromium with it. The fonts are
shipped with the code, not downloaded.

**App updates** come from this project's GitHub releases. The check sends the app's version and nothing else of yours. A signed
and notarized macOS build, the Windows installer and the AppImage download an update in the background and
install it on restart. An unsigned macOS build and the `.deb` do not replace themselves: they say a version is
available and link to the release page. Whether a given release is signed depends on how it was built.

## Problem reports

`logs/door.log` holds one line per failure: a tool's name and its error message, never what it was given. It
holds no CV text, profile values or ad text. `./door data report`, or Settings → Help → Save logs…, packs
it with the last five run records cut to counts and errors, the checks of `doctor`, and the version and
operating system into one `.zip`. Emails, the data folder and your home folder are masked; nothing from
`profile/`, no postings and no ledger go in. It is saved only where you choose and is never sent
automatically: you attach it yourself.

## Reporting a security problem

See [SECURITY.md](../SECURITY.md). Please do not put the details in a public issue. Use the **Report a
vulnerability** button on the repository's Security tab, or email the address in that file. It is a personal
project with no promised response time; only the latest release is supported.

## What it does not protect against

- **Someone with your computer or your account.** Your data folder and `drive.json` are readable by your
  user, and nothing is encrypted. Disk encryption and a screen lock are your protection.
- **Cloudflare.** It sees the phone's traffic, decrypted, as it passes. If that is not acceptable, do not
  set up the phone.
- **The sites, Anthropic and Google.** What you send them is under their own terms and retention. Job
  sites see your requests; Anthropic sees what the `claude` tool sends; Google holds the Drive archive.
- **A job ad that tricks a model.** The gate and the cut-down tools limit what a hostile ad can do, but a
  model can still be misled into a wrong score or a wrong sentence in a letter. Read what you send.
- **Applying for you.** It never submits an application: the sending is yours.
