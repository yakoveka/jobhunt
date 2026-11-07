# Setup

About an hour, most of it answering questions about yourself and checking what the agent wrote. Take the checking seriously: the drafts are only as accurate as your profile.

## 1. Install the prerequisites

```sh
# Claude Code (other methods: https://code.claude.com/docs/en/setup), then log in once:
curl -fsSL https://claude.ai/install.sh | bash
claude

# Python 3.11+ (pick one)
brew install python
mise use -g python@3.13

python3 --version          # must print 3.11 or newer
```

Install Google Chrome if you don't have it (it renders the PDFs). Optional: [Obsidian](https://obsidian.md).

## 2. Get the code and link the skill

```sh
git clone https://github.com/<you>/jobhunt.git ~/jobhunt      # anywhere you like
mkdir -p ~/.claude/skills
ln -s ~/jobhunt ~/.claude/skills/jobs                          # Claude Code now knows /jobs
```

Updating later is just `git -C ~/jobhunt pull`.

## 3. Run the guided setup

Gather first:
- your current CV (PDF, DOCX or Markdown); several versions are even better, because the agent spots where they disagree
- your LinkedIn profile as a PDF (your profile → **More** → **Save to PDF**)
- links: GitHub, portfolio, certificates
- 3–5 things you wrote yourself and liked (a past cover letter, a good email, a post), for the voice guide
- a rough idea of your pay floor and target, where you can work from, and what you refuse

Then start Claude Code in any folder and run:

```
/jobs setup
```

It will:
1. Ask where your **hunt dir** should live. Suggestions: `~/JobHunt`, or a folder inside your Obsidian vault if you want the Kanban board. It then copies the templates there and writes `~/.config/jobhunt/config.toml`.
2. Read your CV, the LinkedIn PDF and the links, and draft `profile/profile.md`. Every claim is marked **[E]** (you can show proof) or **[I]** (self-reported). Where your sources disagree, it asks you, and records the answer under **Corrections**.
3. Interview you about the job you want, a few questions at a time. It writes your answers to `criteria.md`: goal and deadline, pay floor/target and net-vs-gross, role families, work modes and location, languages, hard-nos, CV rules, ready answers for forms.
4. Draft `profile/stories.md` (STAR stories), `profile/voice.md` (from your writing samples) and `cv-master.html` (a CV with more bullets than fit on a page, each one recording which profile item it came from).
5. Tune `sources.toml` to your stack and location, suggest companies whose career feeds to watch, and run a test fetch.

You can stop at any point. Running `/jobs setup` again continues from what's missing. Anything it couldn't find out is marked `TODO(ask)`, and the final checklist lists those items.

### Doing it by hand instead

```sh
python3 ~/.claude/skills/jobs/jobhunt.py init ~/JobHunt
```

Then edit the files in `~/JobHunt` (each template explains itself and shows an example persona) and `~/.config/jobhunt/config.toml`.

## 4. Review: the step that matters

Read these yourself, line by line:
- **`profile/profile.md`**: is every claim true, and is the [E]/[I] marking honest? Add what's missing. Put anything an old CV gets wrong under **Corrections**.
- **`cv-master.html`**: open it in a browser. It should read like your best CV, with extra bullets. Fix any wording you wouldn't say out loud in an interview.
- **`criteria.md`**: especially the hard-nos, the pay floor and the CV rules (e.g. a confidential employer you must not name).

What makes a good profile:
- Prefer evidence you could show an interviewer: a repo, a commit count, a public page, a metric from a dashboard. Write down where it lives.
- Write achievements, not duties: "cut p95 latency from 900 ms to 250 ms", not "responsible for performance".
- Be explicit about weak spots ("Kubernetes: course only, no production"). The agent then frames those gaps honestly instead of overclaiming.

## 5. Try one application

Find a real listing you'd apply to and run:

```
/jobs draft https://example.com/jobs/123
```

Open the folder it prints and read `fit.md`, `cv.html` and `cover-letter.html`. When something is off, fix the source (profile, criteria, voice), not just the draft, so the next drafts improve. Then render the PDFs:

```sh
python3 ~/.claude/skills/jobs/jobhunt.py render
```

## 6. Schedule the daily run

```sh
~/.claude/skills/jobs/install.sh          # daily at 08:40; or e.g. install.sh 07:30
```

- The first run starts immediately. macOS asks whether **JobHunt** may access your Documents (or Desktop, iCloud) folder: click **Allow**. If you never see the prompt and the log says "Operation not permitted", go to System Settings → Privacy & Security → Files and Folders (or Full Disk Access) and enable JobHunt.
- A run takes 15–40 minutes. When it's done you get a notification: "Job hunt: N new · D drafted · F follow-ups".
- If the Mac is asleep at the scheduled time, the run starts when it wakes. It runs at most once a day.

## Daily routine

1. Open `daily/<today>.md` from the notification.
2. For each draft: skim `fit.md`, check `cv.pdf` / `cover-letter.pdf`, and apply using the "How to apply" section. Then set `status: sent` in its `job.md`, or tell `/jobs` "sent Acme", or drag the card in Obsidian.
3. Send the follow-ups drafted in the digest. When anyone replies, update the status (`screen`, `interview`, `rejected`, …).
4. On Mondays, read `market/<week>.md` and tell `/jobs` which proposals to apply.
5. `/jobs status` gives you a summary at any time. `dashboard.md` has the charts.

## Operate

| What | How |
|---|---|
| Run now | `~/.claude/skills/jobs/run-daily.sh --force` |
| Logs | `~/.local/state/jobhunt/logs/<date>.log` |
| Change the time | `install.sh HH:MM` |
| Pause / remove the schedule | `~/.claude/skills/jobs/uninstall.sh` (keeps all your data) |
| Change targeting | edit `criteria.md` / `sources.toml`, or accept proposals from the weekly review |
| Change goal dates or pace | `[goal]` in `~/.config/jobhunt/config.toml` |
| Profile notes elsewhere (e.g. existing notes in a vault) | list them under `profile` in the config, relative to the hunt dir: `profile = ["../me/profile.md", "../me/roles/*.md"]` |

## Troubleshooting

- **"config … not found"**: run `/jobs setup` or `jobhunt.py init <dir>`. A config somewhere else can be selected with `JOBHUNT_CONFIG=/path/config.toml`.
- **`ModuleNotFoundError: tomllib`**: `python3` is older than 3.11 (see step 1).
- **0 new listings for days**: check "Source health" in the digest and the per-source `rejected=` counts in the log. Loosen the regexes in `sources.toml`.
- **Hundreds of irrelevant listings**: tighten `title_exclude` or `stack`. The agent still reads every row, which makes the run slower.
- **No PDFs**: Chrome must be at `/Applications/Google Chrome.app`. Run `jobhunt.py render` and read the error.
- **No notification**: System Settings → Notifications → Script Editor → allow.
