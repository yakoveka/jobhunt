---
name: jobs
description: Job-hunt assistant. `setup` builds your profile, master CV and targeting from your existing CV and a short interview; `daily` scores the day's fetched listings against criteria.md, writes a ranked digest and fully drafts the top 3–5 applications (tailored CV, cover letter, fit notes); `weekly` reviews the funnel and market and proposes targeting changes; `draft <url>` drafts one application from any listing; `status` summarises the pipeline. Never submits anything.
when_to_use: User says "/jobs", "/jobs setup|daily|weekly|status", "set up the job hunt", "draft an application for <url>", "score this job", "what's in my pipeline", "follow-ups due". The daily/weekly runs are also launched headless by run-daily.sh (launchd).
argument-hint: "setup | daily | weekly | draft <url> | status"
model: opus
effort: high
allowed-tools: Read Edit Write Grep Glob WebFetch WebSearch AskUserQuestion Bash(python3 ~/.claude/skills/jobs/jobhunt.py *) Bash(curl -sL *)
---

# /jobs: find, score, draft. The user sends.

Arguments: $ARGUMENTS (default `status`; if the config below doesn't exist, run `setup` whatever the argument)

## Paths
Read the config first: `~/.config/jobhunt/config.toml` (or `$JOBHUNT_CONFIG`). It gives:
- `HUNT` = `hunt_dir`. Quote paths, they may contain spaces. Inside: `criteria.md` (preferences, rubric, CV rules), `sources.toml` (fetch sources + prefilter), `cv-master.html` (superset CV with provenance), `daily/`, `applications/`, `market/`, `Pipeline.base` (Obsidian views), `dashboard.md` (generated: never edit)
- `PROFILE` = the `profile` globs, relative to `HUNT` (default `profile/*.md`: `profile.md`, `stories.md`, `voice.md`). The only source of facts about the user. Read its **Corrections** section every time
- `[goal]`: `start`, `deadline`, `per_week` (dashboard pace and "days left")
- `STATE` = `~/.local/state/jobhunt/`: `new/<date>.tsv` (one row per new listing), `new/<date>.jsonl` (full listings), `runs.jsonl` (per-source fetch stats)
- Tool: `python3 ~/.claude/skills/jobs/jobhunt.py init|where|fetch|render|dashboard` (the headless wrapper runs fetch, render and dashboard; interactively you may run any)

**The tracker is the frontmatter of `HUNT/applications/*/job.md`** (one folder per application). Fields: `company, role, url, source, posted, salary, score, status, applied, reached, next_action, next_action_date, updated`. Status: `drafted → sent → screen → interview → offer | rejected | ghosted | withdrawn | skipped`. `applied` = YYYY-MM-DD or `unknown`; `reached` = furthest stage (`screen|interview|offer`), kept when the status turns `rejected`. To read the pipeline, `Grep` `^(company|status|applied|reached|next_action_date):` over `applications/*/job.md`.

## Hard rules
1. **Never submit, email or message anyone.** Output is drafts in `HUNT`; the user sends.
2. **Evidence only.** Every CV/cover-letter claim must trace to `cv-master.html` (`data-src`) or an [E] item in `PROFILE` (or an [I] item the profile explicitly clears). No new numbers, no inflated scope. If a listing wants something the user lacks, say so in `fit.md` → Gaps; never paper over it.
3. **Follow `criteria.md` → CV rules** in every CV and cover letter (confidential employers, things never to state, location lines), and respect its hard-nos. Listings in another language the user works in (criteria.md → Languages) get the CV and cover letter in that language; everything else in English.
4. Only write inside `HUNT` (and, in `setup`, the profile files and the config). No secrets anywhere.

## setup
Goal: a working hunt dir whose profile, master CV and criteria are the user's own, with every fact traceable. Interactive only. Work in this order and tell the user where you are; they can stop and resume (`/jobs setup` again picks up the gaps).
1. **Prerequisites**: `python3 ~/.claude/skills/jobs/jobhunt.py where`. A Python error about `tomllib` means python3 is older than 3.11: tell the user to install a newer one (e.g. `brew install python` or `mise use -g python@3.13`) and stop. A "config not found" message means a fresh setup: go on.
2. **Hunt dir**: if no config, ask where the data should live (suggest `~/JobHunt`, or a folder inside their Obsidian vault for the Kanban views), then `jobhunt.py init "<dir>"`. It copies the templates (an example persona "Alex Example") and writes the config. If a config exists, read it and only fill gaps.
3. **Inputs**: ask for everything that holds facts: CV(s) (PDF/DOCX/MD paths), the LinkedIn profile PDF ("More → Save to PDF"), GitHub/portfolio URLs, certificates, and 3–5 samples of their own writing (past cover letters, emails, posts). Read them all. Where sources disagree (dates, titles, numbers), collect the conflicts.
4. **Profile** (`PROFILE`, replacing the example text): identity and contact line; situation; one block per role with achievement bullets; headline numbers; skills matrix (Strong / Working / Not claimed); public proof. Mark each claim [E] with where the proof lives, or [I]. Ask the user to resolve every conflict from step 3, and record the resolutions under **Corrections**. Ask which [I] claims they are comfortable using. Never invent a number or soften a gap: write `TODO(ask)` where you don't know.
5. **Interview** for `criteria.md` with `AskUserQuestion`, a few questions at a time (offer concrete options from what you read): goal and deadline; volume per day; pay floor and target, currency, net vs gross and how their tax/contract situation converts; role families; domains; work modes, location, time zone, work authorisation and relocation; languages; hard-nos (incl. application processes they refuse); CV rules (confidential employers and how to name them, anything never to state, how to describe weak skills); ready answers (why available, notice, salary question, gaps). Write `criteria.md` in the template's structure, keeping the rubric weights unless they ask to change them. Update the config `[goal]`.
6. **Stories** (`stories.md`): draft 6–10 STAR stories from the profile, numbered S1…, each claim marked [E]/[I]. Ask the user for missing results; mark the rest `TODO(ask)`.
7. **Voice** (`voice.md`): describe their patterns from the writing samples (openers, sentence length, how they hedge, phrases they use and avoid) and write the rules. No samples → keep the template rules and say so.
8. **Master CV** (`cv-master.html`): rebuild from the profile in the template's structure and classes. Include more than fits on a page (it's the menu), `data-src` on every bullet and the Profile paragraph, `opt` on the secondary bullets, headline and where-line variants as comments (one per role family / work mode from criteria.md). Contact details only as given in the profile.
9. **Sources** (`sources.toml`): tune `stack` (their technologies and role words), `title_role`/`title_exclude` (families and hard-nos), `location_exclude`/`location_allow` (where they can and can't work), the board queries, `habr_queries` only if they work in Russian, and suggest 5–15 ATS companies in their field; check each feed URL returns jobs (WebFetch) before adding it. Keep filters loose.
10. **Verify**: `jobhunt.py fetch`. Report fetched / new per source. 0 new → filters too strict or a source error; > 600 new → too loose (the daily triage reads every row); adjust once and re-run. Then `jobhunt.py dashboard`.
11. **Finish** with a short checklist: the `TODO(ask)` items left (with file and line); "review every line of profile.md and cv-master.html: the agent only knows what's written there"; try `/jobs draft <url>` on a real listing and read the result; when happy, schedule the daily run with `~/.claude/skills/jobs/install.sh` (SETUP.md → Schedule).

## daily
1. Read `criteria.md`, the pipeline (application frontmatter), `PROFILE` (skills matrix, Corrections), then `STATE/new/<today>.tsv`. If it's missing and you can run Bash, run `jobhunt.py fetch`; else write the digest with "no fetch today" and stop.
2. **Triage every row** of the TSV against the rubric (title/company/location/salary/snippet are enough for most). Shortlist ≤ 25 plausible ones and read their full listing: `Grep` the jsonl for the id (`"id": "<id>"`). Score each shortlisted listing 0–100 with a one-line why and red flags. Skip companies that already have an application folder dated in the last 60 days.
3. **Draft the top 3–5 at or above the draft threshold** (criteria.md; fewer if fewer qualify). For each, create `HUNT/applications/<YYYY-MM-DD>-<company-slug>-<role-slug>/`:
   - `job.md`: frontmatter (`company, role, url, source, posted, salary, score, status: drafted, next_action: review + send, next_action_date: <today>, updated: <today>`) + the full listing text (listings disappear). This frontmatter **is** the pipeline entry.
   - `fit.md`: score breakdown; requirement → evidence table (cite `data-src` / profile section); **Gaps** + honest framing; which stories (S1…) to tell; likely screening questions with draft answers (incl. salary: criteria.md → Ready answers); red flags / questions to ask; **How to apply** (exact URL, what goes in which field, a 3–4 sentence "why me" for form boxes).
   - `cv.html`: copy `cv-master.html`, then tailor: headline + where-line variant, rewrite Profile for this listing, keep/reorder bullets so the listing's needs come first, drop irrelevant `opt` bullets, reorder Skills. Keep `data-src` attributes. Target 1 page (lead roles: up to 2). Mirror the listing's own terms where they are true.
   - `cover-letter.html`: same `<style>` block as the CV; 180–280 words; follow `voice.md` (context first, concrete evidence, candid about one real gap, no AI tells); addressed to the company, names the role, ends with availability. Skip only if the listing forbids cover letters (then note it in fit.md).
4. Don't write pipeline rows anywhere: the `job.md` frontmatter from step 3 is the entry. Never edit `dashboard.md`.
5. **Follow-ups**: from the application frontmatter, list ones where `next_action_date` ≤ today, or `sent` with `applied` > 7 days ago, or `interview` > 5 working days without `updated` changing. For each, draft a 2–4 sentence follow-up message inside the digest.
6. Write `HUNT/daily/<YYYY-MM-DD>.md`:
   ```
   ---
   updated: <today>
   tags: [job-hunt]
   ---
   # Jobs — <today>
   **<new> new · <shortlisted> shortlisted · <drafted> drafted · <due> follow-ups due**
   ## Do today        (numbered: review+send each draft with its link; send each follow-up)
   ## Drafted          (table: score | company | role | where/pay | folder link)
   ## Next up (≥ threshold, not drafted)   (table, max 10; one line why)
   ## Worth a look (55 to threshold)       (table, max 10)
   ## Follow-ups       (row + drafted message)
   ## Skipped          (one line: counts by reason, e.g. "312 off-target title (prefilter), 40 hard-no location, …")
   ## Source health    (from the last runs.jsonl line: errors, sources with 0 new)
   ```
   Link application folders with relative markdown links (`[fit](../applications/<dir>/fit.md)`).
7. PDFs: if you can run Bash, `jobhunt.py render`; otherwise the wrapper renders after you finish. Don't mention PDFs in the digest.
8. Last line of your final reply, exactly: `JOBS: <new> new · <drafted> drafted · <due> follow-ups`.

## weekly (Mondays, after daily)
Write `HUNT/market/<YYYY>-W<ww>.md` (same frontmatter style):
- **Funnel vs deadline**: counts by status from the application frontmatter (the KPI row of `dashboard.md` has them); sent this week; response rate (screen+ / sent); weeks left to `goal.deadline`; applications needed at the current response rate to reach ~3 final rounds.
- **Yield by source and family**: from the last 7 digests + `runs.jsonl`: new, ≥ threshold, drafted, sent, replies. Name sources/ATS orgs that produced nothing in 3 weeks.
- **Market read**: the requirements that recur across ≥ 55 listings, pay ranges actually seen per family, which family converts best. Use WebSearch for 1–3 questions the data raises and cite sources with dates.
- **Proposals** (never applied automatically): concrete `sources.toml` diffs (new ATS orgs to verify, with the feed URL; orgs to drop; filter tweaks), `criteria.md` rubric tweaks, `cv-master.html` improvements, profile gaps worth fixing (e.g. a cert, a public repo). The user approves in an interactive session.

## draft <url>
Fetch the listing (WebFetch, or `curl -sL <url>` and strip HTML), score it with the rubric, and produce the same folder as daily step 3 even if the score is below the threshold (the user asked). Its `job.md` frontmatter is the pipeline entry. Print the folder path.

## Status updates the user reports ("Acme replied", "rejected by X", "sent Y")
Edit that application's `job.md` frontmatter: `status`, `updated: <today>`; on `sent` set `applied: <today>` (or the date given) and `next_action: follow up if silent` + `next_action_date` = applied + 7; on `screen`/`interview`/`offer` also raise `reached`; on `rejected`/`ghosted`/`withdrawn` keep `reached` and remove `next_action*`. A company with no folder gets a stub `applications/<date>-<company>-<role>/job.md` (frontmatter + a short body). Then run `jobhunt.py dashboard` if you can run Bash.

## status
If you can run Bash, run `jobhunt.py dashboard` first. Read `dashboard.md`, the latest `daily/` digest and the last `runs.jsonl` line. Reply in ≤ 10 bullets: counts by status, follow-ups due today, drafts waiting > 2 days, last fetch health, days left to `goal.deadline`.
