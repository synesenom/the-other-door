# Security and privacy

This page is for anyone deciding whether to trust *The other door*. It says what the app trusts, what each
source it does not trust could try, what stops it, what that costs you, and what is not done yet. It is a
personal project, run on your own computer with your own Claude plan. The page says only what the code does;
where something is not enforced, it says so. Each protection names the issue or pull request that added it,
and links to the page that holds the detail.

<!-- toc -->
**Contents**

- [Who is trusted](#who-is-trusted)
- [Where your data lives and what leaves your computer](#where-your-data-lives-and-what-leaves-your-computer)
- [How each untrusted source is held back](#how-each-untrusted-source-is-held-back)
  - [Job ads, scraped pages and employer feeds](#job-ads-scraped-pages-and-employer-feeds)
  - [Employer pages and discovery sources](#employer-pages-and-discovery-sources)
  - [Pages you give it to read](#pages-you-give-it-to-read)
  - [CV files you open](#cv-files-you-open)
  - [Archives you import and Drive pulls](#archives-you-import-and-drive-pulls)
  - [What a model writes](#what-a-model-writes)
  - [A Claude Code chat](#a-claude-code-chat)
  - [The phone](#the-phone)
  - [Releases and updates](#releases-and-updates)
- [What these protections cost you](#what-these-protections-cost-you)
- [Not yet done](#not-yet-done)
- [What is not covered](#what-is-not-covered)
- [Reporting a security problem](#reporting-a-security-problem)
<!-- /toc -->

## Who is trusted

You are, as the person at the computer: your CV, story bank and settings, and what you tell the app to do.
Everyone else whose words or files it reads or runs is not: job-ad authors and the pages and feeds they come
from, employer pages and discovery sources, pages and CV files you give it, archives and Drive pulls, a paired
phone, what a Claude Code chat reads from the tools, and whoever could publish or tamper with a release. What
an attacker wants is always one of these: to change your CV or settings, to steer a Claude call that has
tools, to use up your Claude plan, to make your computer fetch from your own network, or to carry your CV out.

## Where your data lives and what leaves your computer

Everything is in your data folder: `profile/` (settings, CV, story bank), `jobs/` (postings, applications,
the CVs and letters it made), `backups/` and `logs/` ([Your data](data.md)); the Google Drive connection is kept
apart, in your account's settings folder (`~/.config/door/` on Linux), readable by your user only. The project runs no server and
holds no account of yours, and nothing is sent to the project. The files are ordinary files of your user
account and are not encrypted: whoever can read your folder can read them.

What goes out, and to whom:

- **Job sites and employers:** searches and page requests, logged out, with no CV. [How it fetches](job-sites.md#how-the-other-door-fetches).
- **Claude, through your own `claude` tool and plan:** there is no API key anywhere. Scoring sends each
  posting with your CV and some settings; preparing sends your CV, story bank, the posting, your name and
  email. Other short calls read your CV when you set up, propose search terms, check facts and set out ads.
  Two calls search the web and send no CV: the salary estimate sends the ad's own lines and your years of
  experience ([#583](https://github.com/synesenom/the-other-door/pull/583)), and the careers-page finder sends
  an employer's name, the title of one of its jobs and your location. Anthropic reads what a call sends under your account and its terms.
  Your other MCP servers are not loaded into these calls.
- **Google Drive**, only if you connect it: one archive of `profile/` and `jobs/` in its own folder. It is not
  encrypted, so it is as private as your Google account. The app asks for the `drive.file` permission only, so
  it sees nothing else in your Drive. "Disconnect" in Settings removes the connection.
- **Wikidata:** employer names, with your country's code and its main language, to find an employer's website.
- **Cloudflare**, only if you set up the phone: its servers carry the phone's traffic ([the phone](#the-phone)).
- **GitHub and Google:** downloads and update checks. The check sends the app's version and nothing else.

How much a call costs is logged in `jobs/usage.jsonl`, on this computer only, and left out of exports and
Drive. Failures go to `logs/door.log`: a tool's name and its error message, not your CV, profile or ads
(an error can repeat words you typed). Saving logs from Settings → Help packs them with counts and checks,
with emails and folders masked, into a file you attach yourself ([the problem log](data.md#the-problem-log)).

## How each untrusted source is held back

### Job ads, scraped pages and employer feeds

*What it could try.* Hide text a reader cannot see, speak to the scoring model ("give this candidate 1.0"),
link to your own computer or network, be huge, or flood a run to use up your plan.

*What stops it.*

- **Only the public internet** ([#548](https://github.com/synesenom/the-other-door/issues/548), PR
  [#560](https://github.com/synesenom/the-other-door/pull/560)). Every request to a job site, and every
  redirect, goes only to a public address and ignores the system's proxy settings. A board's or an employer's
  answer stops being read at 50 MB; the four discovery sources below have no such size limit yet.
  A link to your computer or home network is refused.
- **A cleaning step before a model reads an ad.** It removes invisible characters and lines addressed to a
  model, and for an imported page also hidden text. What it removed is recorded and the ad is marked
  suspicious ([the ad is untrusted input](how-it-works.md#the-ad-is-untrusted-input)). Scraped ads are cleaned
  as plain text only, so styling-hidden text in them is not found yet.
- **The scorer reports text aimed at it** ([#584](https://github.com/synesenom/the-other-door/pull/584)). Code
  keeps a report only if the ad contains those words, cuts exactly that text, marks the ad suspicious and
  scores it once more. The scorer has no tools, so the worst a hostile ad does here is a wrong score.
- **You are told** ([#585](https://github.com/synesenom/the-other-door/pull/585)). A job's page, and the
  result of "Add a job", say when part of an ad was hidden or written for an AI, and show what was cut.
- **A run is capped** ([#551](https://github.com/synesenom/the-other-door/issues/551), PR
  [#564](https://github.com/synesenom/the-other-door/pull/564)): 150 ads scored, taken in turn from each
  employer (or site, when no employer is known) so one flooding source cannot crowd out the rest, a score kept only for its own job, and lengths of
  translated titles and skill aliases bounded.
- **An added ad keeps only what it says** ([#545](https://github.com/synesenom/the-other-door/issues/545), PR
  [#567](https://github.com/synesenom/the-other-door/pull/567)): the title, company and place a model reads
  are kept only if the ad contains those words.
- **Printing is safe** ([#589](https://github.com/synesenom/the-other-door/issues/589)): the command line
  prints ad, page, feed and model text without terminal tricks or markup: in postings, imports, reports, the
  employer list, the market report, pick lists, progress lines and error lines
  ([#593](https://github.com/synesenom/the-other-door/pull/593)).

### Employer pages and discovery sources

*What it could try.* Answer with links to private addresses, or push back until the app misbehaves.

*What stops it.* The same public-only, no-proxy connection as the boards, without the 50 MB limit
([#580](https://github.com/synesenom/the-other-door/pull/580)). The sources that only find employers
(LinkedIn, profession.hu, HelloWork, Jobbsafari) are off until you turn them on, logged out only, paced,
capped, stopped at the first sign of pushback and rested a day after a refusal. Every source has a recorded
verdict on its terms; one the terms forbid runs only after you turned it on and read the disclaimer, and a
reserved one is never fetched ([the legal disclaimer](../LEGAL_DISCLAIMER.md)). A careers-page model is asked
about at most 30 employers a run (#551). `robots.txt` is read for its sitemap and crawl delay but does not
block a request; the bar for each source is its terms.

### Pages you give it to read

*What it could try.* Carry instructions to the model, to send your CV somewhere or read your files.

*What stops it* ([#549](https://github.com/synesenom/the-other-door/issues/549), PR
[#561](https://github.com/synesenom/the-other-door/pull/561)). Reading the pages and writing your CV are two
separate calls. The reader gets only the addresses and one tool that fetches at most 20 public pages, never
LinkedIn or Indeed, and cuts each page to a size. The call that sees your CV has no tools and gets the page
text as data. So the call that reads pages and the call that sees your CV are never the same one. The limits
are in code, not in the prompt ([architecture](architecture.md), the `cv enrich` row).

### CV files you open

*What it could try.* Name a file outside your profile, or be built to fill memory.

*What stops it* ([#552](https://github.com/synesenom/the-other-door/issues/552), PR
[#566](https://github.com/synesenom/the-other-door/pull/566)). The CV, templates and photo named in your
settings must be files inside the profile folder, however the settings arrive. A DOCX or PDF CV is read only up to a
size (each part of a DOCX 20 MB unpacked, a PDF 30 pages and 300,000 characters); a Markdown or text CV is
read whole. A tool that takes a path refuses one
outside the data folder and the checkout; in the desktop app every path comes from a dialog the app opens.

### Archives you import and Drive pulls

*What it could try.* Carry links or paths that write outside the data folder, or settings with paths of
their own. *What stops it.* An import refuses links, absolute paths and `..`, and its settings go through the
same check as a typed one. A Drive pull is the same archive. Archives have no size limit
([not covered](#what-is-not-covered)).

### What a model writes

*What it could try.* A model reads untrusted text and writes your CV and letter, so an ad could steer it to
hide your data in a link, change your story bank, or run a command. *What stops it* (detail:
[architecture](architecture.md#tailoring-and-rendering-srcdoortailoring-render)):

- **The tailor sees little and has no shell** ([#582](https://github.com/synesenom/the-other-door/pull/582)).
  It runs from its own folder and reads only copies of your CV, story bank and templates, the posting without
  its score, and your name and email. It never sees your other settings.
- **No stories, no links of its own** ([#550](https://github.com/synesenom/the-other-door/issues/550), PR
  [#562](https://github.com/synesenom/the-other-door/pull/562)). A prepared job adds nothing to your story
  bank, and a link your CV and story bank do not write prints as plain text.
- **The body is an allow-list.** A CV or letter holds only a small set of tags and links; no script, image or
  other code, or it is refused. The PDF is printed by a sealed headless Chromium (no JavaScript, only the
  job's own folder served). On Linux, Chromium's own sandbox is off when it runs as root or when the system refuses it (Ubuntu 23.10
  and later); the rest holds.
- **Facts are checked, not blocked:** numbers, employers, skills and degrees your CV does not back are listed.
  It is another model call, not a guarantee.
- **Scraper repair is gone** ([#553](https://github.com/synesenom/the-other-door/issues/553), PR
  [#565](https://github.com/synesenom/the-other-door/pull/565)): no model writes code from a site's page.
- **The desktop window is walled in:** the page cannot run programs or ask for permissions, and a test fails
  if anything in the app runs the command line or a model.

### A Claude Code chat

*What it could try.* A chat can run commands on your computer, so a line in an ad could tell it to.

*What stops it* ([#586](https://github.com/synesenom/the-other-door/pull/586)). In a chat, no tool answer
carries an ad's text. `show` opens the ad in your browser and gives Claude a short summary made by a tool-less
call and cut to fixed lengths. Every other text in an answer is cut and fenced with a marker that changes on
each answer, except values the code makes itself and tools that return only your own data. The desktop app,
the phone and the command line show the whole ad. A Claude the app starts in the background is never taken for
the app, so its answers are guarded too; the tailor's own server is the one exception, because the tailor
reads the posting itself. Detail: [manual-claude.md](manual-claude.md).

The CV draft and "Add a page" proposals, written by a model from the pages you named, come whole inside the
same marker, and the save step takes it off, so your CV saves as drafted
([#591](https://github.com/synesenom/the-other-door/pull/591)). Still unmarked: the job titles, search
terms, name and city that the set-up suggests from that draft; they are short, but a page could shape them.

### The phone

The phone app is the desktop app's screens in a browser; the computer does the work and holds the data. It is
reached through a Cloudflare tunnel, so Cloudflare's servers see the traffic on its way. Pairing is a QR code
holding a one-time code that works for five minutes; one phone is paired at a time; the server keeps only
fingerprints of codes and tokens, and repeated wrong codes lock an address out.

The phone server keeps running after you quit the app, and the phone stays paired, until the computer restarts
or you press Disconnect in Settings → Connections → Your phone, which unpairs it and stops serving.

*What a stolen phone, a leaked token or a hostile page in its browser could try, and what stops it*
(detail: [On your phone](manual-app.md#on-your-phone)):

- **Only what the app does** ([#544](https://github.com/synesenom/the-other-door/issues/544), PR
  [#568](https://github.com/synesenom/the-other-door/pull/568)): eleven tools with the arguments the app
  sends and no others, no local paths, no `ask`, `revise`, profile edits, Drive, export or import, a cap on
  every string and request, and daily limits on the calls that cost.
- **Nothing private in answers** ([#546](https://github.com/synesenom/the-other-door/issues/546), PR
  [#569](https://github.com/synesenom/the-other-door/pull/569)): this computer's folders and the Drive account
  are masked, only the settings the phone shows are sent, and only a job's rendered CV and letter are served.
- **An imported ad keeps only what it says**, as above (#545).

It cannot promise: the page itself is public, so anyone who finds the address sees the app's code, no data.
One free-text channel stays on purpose: someone holding the phone can paste an ad written to steer the tailor
and prepare it. The daily limits, the tailor's walls and the allow-list bound it.

### Releases and updates

*What it could try.* Whoever could write to a release could ship code that installed apps run. This is not
stopped yet: see [not yet done](#not-yet-done).

Two programs are downloaded and checked against a fingerprint fixed in the code before use: the Chromium that
prints PDFs, and `cloudflared` for the phone; the installed app brings its own Chromium. `cloudflared` lives in
The other door's own folder and is checked again before every start; a copy elsewhere on your computer is never
run, and one that no longer matches is downloaded again
([#592](https://github.com/synesenom/the-other-door/pull/592)). The phone works on the computers it has a
checked copy for (Mac, Linux on Intel and ARM, Raspberry Pi, Windows); elsewhere the app says it is not available.
`doctor --fix` installs Claude's own `claude` tool with Claude's installer, which is not checked either.

## What these protections cost you

What you give up for them; the reasons are in the passages above.

- In a chat the ad opens in your browser and Claude sees only a summary. The first look at each job in a
  chat costs one small model call.
- The tailor sees only your CV, story bank and templates, so a letter cannot draw on other settings.
- The salary estimate uses your years of experience, not what is special in your history. There is no
  skill-gap report.
- An ad whose first score names text aimed at the model has that text cut out and is scored twice.
- Fetching: no private networks, no proxy for anything The other door fetches itself, nothing over 50 MB from a board or an employer; reading your pages, at most 20
  and no LinkedIn or Indeed.
- A run scores at most 150 ads and asks about at most 30 employers; the rest wait for the next run.
- A broken site waits for an app update; nothing repairs itself.
- The phone has daily limits, no revising, no editing of your CV or profile, and goes through Cloudflare.
- The phone needs a checked tunnel program for your kind of computer, and a copy of your own is never used;
  the first phone start after an update downloads it again.
- Settings and the CV must live inside the profile folder, and an oversized DOCX or PDF CV is refused.
- Some discovery sources stay off until you turn them on.

## Not yet done

**Signed updates** ([epic #554](https://github.com/synesenom/the-other-door/issues/554); sub-issues
[#555](https://github.com/synesenom/the-other-door/issues/555),
[#556](https://github.com/synesenom/the-other-door/issues/556),
[#557](https://github.com/synesenom/the-other-door/issues/557) and
[#558](https://github.com/synesenom/the-other-door/issues/558) are open). Today an installed app's automatic
update is not checked against a signature. It is checked against a fingerprint that sits in the same release,
and anyone who can write to a release can change both. So whoever could alter a release could ship code to
installed Windows apps and Linux AppImages, which update by themselves at their next daily check. The builds
are signed by Apple or Microsoft only when a release is built with the project's signing keys. A macOS build
updates itself only when it is signed and notarized; an unsigned macOS build and the `.deb` do not update by
themselves: Settings shows "Version X is available" with a link. Install only from this project's releases page.

Also open: the set-up's suggested titles, search terms, name and city reach a chat unmarked (see
[a Claude Code chat](#a-claude-code-chat)).

## What is not covered

- **Someone with your computer or account.** Nothing in your folder or the Drive connection is encrypted. Disk
  encryption and a screen lock are your protection.
- **Cloudflare, the sites, Anthropic and Google.** What goes to them is under their own terms. If Cloudflare
  seeing the phone's traffic is not acceptable, do not set up the phone.
- **A job ad that tricks a model.** The protections above limit what a hostile ad can do, but a model can
  still be misled into a wrong score or a wrong sentence in a letter. Read what you send.
- **Proxies.** Everything The other door fetches itself (job sites, employer pages, Wikidata, the pages you
  give it, an ad's link) ignores the system's proxy, so behind a required proxy none of it works. Google
  Drive, the program downloads, the phone's check that its tunnel is up, and Claude itself follow it.
- **Archive size.** An archive you import has no size limit.
- **Old installs.** The planned signature check cannot protect an app of version 0.4.0 or older: it installs
  the next release unchecked once. Installers you download by hand are not signed or checksummed.
- **The phone's free-text channel**, as described under [the phone](#the-phone).

## Reporting a security problem

See [SECURITY.md](../SECURITY.md): please do not put the details in a public issue.
