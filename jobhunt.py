#!/usr/bin/env python3
"""jobhunt: deterministic job fetcher + PDF renderer for the /jobs skill.

  jobhunt.py init <hunt_dir>
      Copy templates/ into <hunt_dir> (never overwrites) and write the config if it doesn't exist yet.
  jobhunt.py where
      Print the hunt dir, then any profile dirs outside it (one per line; run-daily.sh reads this).
  jobhunt.py fetch  [--sources F] [--state D] [--date YYYY-MM-DD]
      Pull public job sources, normalise, prefilter, dedupe against earlier runs.
      Writes <state>/new/<date>.jsonl (new candidates) and appends <state>/runs.jsonl.
  jobhunt.py render [--apps D]
      Print every applications/*/{cv,cover-letter}.html whose PDF is missing or stale to PDF
      via headless Google Chrome.
  jobhunt.py dashboard [--apps D] [--out F] [--date YYYY-MM-DD]
      Read applications/*/job.md frontmatter and write <hunt_dir>/dashboard.md (KPIs, sent-by-date
      chart, outcome Sankey, what needs action). Stamps a missing `applied` date on sent+ notes.

Paths and the goal come from ~/.config/jobhunt/config.toml (override: --config or $JOBHUNT_CONFIG).
Stdlib only. The LLM side (scoring, drafting) lives in SKILL.md; this file never judges fit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
CONFIG_FILE = Path(os.environ.get("JOBHUNT_CONFIG", Path.home() / ".config" / "jobhunt" / "config.toml"))
DEFAULT_STATE = Path.home() / ".local" / "state" / "jobhunt"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
UA = "Mozilla/5.0 (Macintosh; personal job search) jobhunt/0.1"
SEEN_TTL_DAYS = 90
DESC_MAX = 6000
# Below this an "annual" USD figure is probably monthly or hourly: too ambiguous to filter on.
MIN_PLAUSIBLE_ANNUAL = 15000

Get = Callable[[str], bytes]
Job = dict


# ---------- helpers ----------

class _Text(HTMLParser):
    BLOCK = {"p", "br", "li", "div", "h1", "h2", "h3", "h4", "tr", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def text(markup: str | None) -> str:
    """HTML → plain text, whitespace-collapsed, truncated to DESC_MAX."""
    if not markup:
        return ""
    p = _Text()
    p.feed(markup)
    lines = (re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in "".join(p.parts).splitlines())
    return "\n".join(ln for ln in lines if ln)[:DESC_MAX]


def iso_date(value) -> str:
    """Best-effort posted date → YYYY-MM-DD ('' if unknown). Accepts ISO strings, RFC 822, epoch s/ms."""
    if value in (None, "", 0):
        return ""
    try:
        if isinstance(value, (int, float)):
            secs = value / 1000 if value > 10**11 else value
            return dt.datetime.fromtimestamp(secs, dt.timezone.utc).date().isoformat()
        s = str(value).strip()
        if re.match(r"\d{4}-\d{2}-\d{2}", s):
            return s[:10]
        return email.utils.parsedate_to_datetime(s).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return ""


def mk(source: str, kind: str, native_id, **kw) -> Job:
    j = {
        "id": f"{source}:{native_id}", "source": source, "kind": kind, "title": "", "company": "",
        "location": "", "url": "", "posted": "", "salary": "", "salary_min_usd": None,
        "salary_max_usd": None, "tags": [], "description": "",
    }
    j.update(kw)
    j["title"] = re.sub(r"\s+", " ", unmojibake(j["title"])).strip()
    j["company"] = unmojibake(j["company"]).strip()
    return j


def unmojibake(s: str) -> str:
    """Repair UTF-8 that a feed double-encoded as Latin-1 (e.g. 'Sothebyâ\\x80\\x99s')."""
    if not re.search("[Â-ô][\u0080-¿]", s):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def usd_range(lo, hi, currency="USD"):
    """Structured salary → (min, max) annual USD, or (None, None) when absent/non-USD."""
    if (currency or "USD").upper() != "USD":
        return None, None
    lo = int(lo) if lo else None
    hi = int(hi) if hi else None
    return lo, (hi or lo)


def salary_text(lo, hi, currency) -> str:
    if not lo and not hi:
        return ""
    return f"{currency or ''} {lo or '?'}–{hi or '?'}".strip()


REQUEST_DEADLINE_S = 90


def http_get(url: str) -> bytes:
    """GET with one retry and a hard total deadline (urlopen's timeout is per socket op, so a trickling
    server could otherwise hang the run forever)."""
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            deadline = time.monotonic() + REQUEST_DEADLINE_S
            chunks = []
            with urllib.request.urlopen(req, timeout=20) as r:
                while chunk := r.read(1 << 16):
                    chunks.append(chunk)
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"exceeded {REQUEST_DEADLINE_S}s total: {url}")
            return b"".join(chunks)
        except Exception as e:  # noqa: BLE001 — retried once, then surfaced per source
            last = e
            time.sleep(2 * (attempt + 1))
    raise last  # type: ignore[misc]


def get_json(get: Get, url: str):
    return json.loads(get(url))


def rss_items(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw)
    return [{c.tag: (c.text or "") for c in it} for it in root.iter("item")]


# ---------- sources: (cfg, get) -> list[Job] ----------

def src_remoteok(cfg, get: Get) -> list[Job]:
    out = []
    for r in get_json(get, "https://remoteok.com/api"):
        if "id" not in r:
            continue  # first row is the legal notice
        lo, hi = usd_range(r.get("salary_min"), r.get("salary_max"))
        out.append(mk("remoteok", "board", r["id"], title=r.get("position", ""), company=r.get("company", ""),
                      location=r.get("location") or "Remote", url=r.get("url", ""), posted=iso_date(r.get("date")),
                      salary=salary_text(r.get("salary_min"), r.get("salary_max"), "USD"),
                      salary_min_usd=lo, salary_max_usd=hi, tags=r.get("tags") or [],
                      description=text(r.get("description"))))
    return out


def src_himalayas(cfg, get: Get) -> list[Job]:
    out = []
    for q in cfg["boards"].get("himalayas_queries", []):
        url = "https://himalayas.app/jobs/api/search?" + urllib.parse.urlencode({"q": q, "sort": "recent"})
        for r in get_json(get, url).get("jobs", []):
            cur = r.get("currency") or "USD"
            lo, hi = usd_range(r.get("minSalary"), r.get("maxSalary"), cur)
            out.append(mk("himalayas", "board", r.get("guid"), title=r.get("title", ""),
                          company=r.get("companyName", ""),
                          location=", ".join(r.get("locationRestrictions") or []) or "Worldwide",
                          url=r.get("guid") or r.get("applicationLink", ""), posted=iso_date(r.get("pubDate")),
                          salary=salary_text(r.get("minSalary"), r.get("maxSalary"), cur),
                          salary_min_usd=lo, salary_max_usd=hi,
                          tags=(r.get("categories") or []) + (r.get("seniority") or []),
                          description=text(r.get("description") or r.get("excerpt"))))
    return out


def src_wwr(cfg, get: Get) -> list[Job]:
    out = []
    for cat in cfg["boards"].get("wwr_categories", []):
        for it in rss_items(get(f"https://weworkremotely.com/categories/{cat}.rss")):
            company, _, title = it.get("title", "").partition(": ")
            if not title:
                company, title = "", company
            out.append(mk("wwr", "board", it.get("guid") or it.get("link"), title=title, company=company,
                          location=it.get("region") or "Remote", url=it.get("link", ""),
                          posted=iso_date(it.get("pubDate")), tags=[it.get("category", "")],
                          description=text(it.get("description"))))
    return out


def src_remotive(cfg, get: Get) -> list[Job]:
    out = []
    for cat in cfg["boards"].get("remotive_categories", []):
        for r in get_json(get, f"https://remotive.com/api/remote-jobs?category={cat}").get("jobs", []):
            out.append(mk("remotive", "board", r.get("id"), title=r.get("title", ""), company=r.get("company_name", ""),
                          location=r.get("candidate_required_location") or "Remote", url=r.get("url", ""),
                          posted=iso_date(r.get("publication_date")), salary=r.get("salary") or "",
                          tags=r.get("tags") or [], description=text(r.get("description"))))
    return out


def src_workingnomads(cfg, get: Get) -> list[Job]:
    out = []
    for r in get_json(get, "https://www.workingnomads.com/api/exposed_jobs/"):
        out.append(mk("workingnomads", "board", r.get("url"), title=r.get("title", ""),
                      company=r.get("company_name", ""), location=r.get("location") or "Remote",
                      url=r.get("url", ""), posted=iso_date(r.get("pub_date")),
                      tags=[t for t in (r.get("tags") or "").split(",") if t],
                      description=text(r.get("description"))))
    return out


def src_jobicy(cfg, get: Get) -> list[Job]:
    out = []
    for ind in cfg["boards"].get("jobicy_industries", []):
        data = get_json(get, f"https://jobicy.com/api/v2/remote-jobs?count=100&industry={ind}")
        for r in data.get("jobs", []):
            cur = r.get("salaryCurrency") or "USD"
            lo, hi = usd_range(r.get("annualSalaryMin"), r.get("annualSalaryMax"), cur)
            out.append(mk("jobicy", "board", r.get("id"), title=html.unescape(r.get("jobTitle", "")),
                          company=r.get("companyName", ""), location=r.get("jobGeo") or "Remote",
                          url=r.get("url", ""), posted=iso_date(r.get("pubDate")),
                          salary=salary_text(r.get("annualSalaryMin"), r.get("annualSalaryMax"), cur),
                          salary_min_usd=lo, salary_max_usd=hi,
                          tags=(r.get("jobIndustry") or []) + (r.get("jobLevel") or "").split(", "),
                          description=text(r.get("jobDescription") or r.get("jobExcerpt"))))
    return out


def src_hn(cfg, get: Get) -> list[Job]:
    """Top-level comments of the latest 'Ask HN: Who is hiring?' thread."""
    stories = get_json(get, "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=10")
    story = next((s for s in stories.get("hits", []) if s.get("title", "").startswith("Ask HN: Who is hiring?")), None)
    if not story:
        return []
    sid = int(story["objectID"])
    out, page, pages = [], 0, 1
    while page < pages and page < 5:
        data = get_json(get, f"https://hn.algolia.com/api/v1/search?tags=comment,story_{sid}&hitsPerPage=1000&page={page}")
        pages = data.get("nbPages", 1)
        page += 1
        for c in data.get("hits", []):
            if c.get("parent_id") != sid or not c.get("comment_text"):
                continue
            body = text(c["comment_text"].replace("<p>", "\n", 1))
            head, _, rest = body.partition("\n")
            segs = [s.strip() for s in head.split("|")]
            out.append(mk("hn", "hn", c["objectID"], title=" | ".join(segs[1:])[:200] or head[:200],
                          company=segs[0][:80], location=head, posted=iso_date(c.get("created_at")),
                          url=f"https://news.ycombinator.com/item?id={c['objectID']}", description=body))
    return out


def src_habr(cfg, get: Get) -> list[Job]:
    out = []
    for q in cfg["boards"].get("habr_queries", []):
        url = "https://career.habr.com/vacancies/rss?" + urllib.parse.urlencode({"q": q, "type": "all", "remote": "true"})
        for it in rss_items(get(url)):
            raw = re.sub(r"^Требуется\s*", "", it.get("title", ""))
            m = re.match(r"«(.+?)»\s*(.*)$", raw)  # «Role» (City)
            title = f"{m.group(1)} {m.group(2)}" if m else raw.strip("«» ")
            desc = it.get("description", "")
            out.append(mk("habr", "board", it.get("guid") or it.get("link"), title=title, company=it.get("author", ""),
                          location="Можно удалённо" if "удалённо" in desc else "", url=it.get("link", ""),
                          posted=iso_date(it.get("pubDate")), tags=re.findall(r"#([\w.+-]+)", desc),
                          description=text(desc)))
    return out


def src_greenhouse(cfg, get: Get) -> list[Job]:
    out = []
    for org in cfg["ats"].get("greenhouse", []):
        for r in get_json(get, f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs?content=true").get("jobs", []):
            out.append(mk("greenhouse", "ats", f"{org}:{r['id']}", title=r.get("title", ""), company=org,
                          location=(r.get("location") or {}).get("name", ""), url=r.get("absolute_url", ""),
                          posted=iso_date(r.get("first_published") or r.get("updated_at")),
                          description=text(html.unescape(r.get("content") or ""))))
    return out


def src_ashby(cfg, get: Get) -> list[Job]:
    out = []
    for org in cfg["ats"].get("ashby", []):
        data = get_json(get, f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true")
        for r in data.get("jobs", []):
            loc = r.get("location") or ""
            if r.get("isRemote"):
                loc = f"{loc} (remote)".strip()
            comp = (r.get("compensation") or {}).get("compensationTierSummary") or ""
            out.append(mk("ashby", "ats", f"{org}:{r['id']}", title=r.get("title", ""), company=org, location=loc,
                          url=r.get("jobUrl", ""), posted=iso_date(r.get("publishedAt")), salary=comp,
                          description=text(r.get("descriptionPlain") or r.get("descriptionHtml"))))
    return out


def src_lever(cfg, get: Get) -> list[Job]:
    out = []
    for org in cfg["ats"].get("lever", []):
        for r in get_json(get, f"https://api.lever.co/v0/postings/{org}?mode=json"):
            out.append(mk("lever", "ats", f"{org}:{r['id']}", title=r.get("text", ""), company=org,
                          location=(r.get("categories") or {}).get("location", ""), url=r.get("hostedUrl", ""),
                          posted=iso_date(r.get("createdAt")),
                          description=text(r.get("descriptionPlain") or r.get("description"))))
    return out


SOURCES: dict[str, Callable] = {
    "remoteok": src_remoteok, "himalayas": src_himalayas, "wwr": src_wwr, "remotive": src_remotive,
    "workingnomads": src_workingnomads, "jobicy": src_jobicy, "hn": src_hn, "habr": src_habr,
    "greenhouse": src_greenhouse, "ashby": src_ashby, "lever": src_lever,
}
# Which config key switches each source on (a truthy bool or a non-empty list).
SOURCE_KEYS = {
    "remoteok": ("boards", "remoteok"), "himalayas": ("boards", "himalayas_queries"),
    "wwr": ("boards", "wwr_categories"), "remotive": ("boards", "remotive_categories"),
    "workingnomads": ("boards", "workingnomads"), "jobicy": ("boards", "jobicy_industries"),
    "hn": ("boards", "hn"), "habr": ("boards", "habr_queries"),
    "greenhouse": ("ats", "greenhouse"), "ashby": ("ats", "ashby"), "lever": ("ats", "lever"),
}


def enabled_sources(cfg) -> dict[str, Callable]:
    return {n: f for n, f in SOURCES.items() if cfg.get(SOURCE_KEYS[n][0], {}).get(SOURCE_KEYS[n][1])}


# ---------- filtering & dedupe ----------

def reject_reason(j: Job, cfg, today: dt.date) -> str | None:
    """Return why a job is dropped before the LLM sees it, or None to keep it."""
    f = cfg["filters"]
    rx = lambda key, s: re.search(f[key], s, re.I)  # noqa: E731
    if not rx("title_role", j["title"]) or rx("title_exclude", j["title"]):
        return "title"
    blob = " ".join([j["title"], " ".join(j["tags"]), j["description"][:4000]])
    if not rx("stack", blob):
        return "stack"
    if rx("location_exclude", j["location"]):
        return "location"
    # ATS feeds and HN mix onsite roles in: require an allowed location, or a relocation/visa phrase in the text.
    if j["kind"] in ("ats", "hn") and not (rx("location_allow", j["location"]) or rx("text_allow", j["description"])):
        return "location"
    if j["posted"]:
        limit = cfg["max_age_days_ats"] if j["kind"] in ("ats", "hn") else cfg["max_age_days"]
        if (today - dt.date.fromisoformat(j["posted"])).days > limit:
            return "age"
    hi = j["salary_max_usd"]
    if hi and MIN_PLAUSIBLE_ANNUAL <= hi < cfg["salary_floor_usd_year"]:
        return "salary"
    return None


def dupkey(j: Job) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9а-я]+", "", s.lower())  # noqa: E731
    return f"{norm(j['company'])}|{norm(j['title'])}"


def run(cfg, state: Path, today: dt.date, get: Get | None, sources: dict | None = None) -> dict:
    """One fetch pass. Returns the run summary (also appended to runs.jsonl)."""
    state.mkdir(parents=True, exist_ok=True)
    seen_path = state / "seen.json"
    seen: dict[str, str] = json.loads(seen_path.read_text()) if seen_path.exists() else {}
    cutoff = (today - dt.timedelta(days=SEEN_TTL_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}

    summary = {"date": today.isoformat(), "sources": {}, "new": 0}
    fresh: list[Job] = []
    for name, fn in (sources if sources is not None else enabled_sources(cfg)).items():
        stat = {"fetched": 0, "kept": 0, "rejected": {}, "error": None, "secs": 0.0}
        summary["sources"][name] = stat
        t0 = time.monotonic()
        try:
            jobs = fn(cfg, get)
        except Exception as e:  # noqa: BLE001 — one broken source must not stop the run
            stat["error"] = f"{type(e).__name__}: {e}"
            continue
        finally:
            stat["secs"] = round(time.monotonic() - t0, 1)
            print(f"  {name}: {stat['secs']}s", file=sys.stderr, flush=True)
        stat["fetched"] = len(jobs)
        for j in jobs:
            why = reject_reason(j, cfg, today)
            if why:
                stat["rejected"][why] = stat["rejected"].get(why, 0) + 1
                continue
            keys = (j["id"], dupkey(j))
            if any(k in seen for k in keys):
                continue
            for k in keys:
                seen[k] = today.isoformat()
            stat["kept"] += 1
            fresh.append(j)

    summary["new"] = len(fresh)
    (state / "new").mkdir(exist_ok=True)
    stem = state / "new" / today.isoformat()
    with open(f"{stem}.jsonl", "a", encoding="utf-8") as fh:
        for j in fresh:
            fh.write(json.dumps(j, ensure_ascii=False) + "\n")
    write_tsv(Path(f"{stem}.tsv"), Path(f"{stem}.jsonl"))
    seen_path.write_text(json.dumps(seen, ensure_ascii=False))
    with open(state / "runs.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return summary


TSV_COLS = ["id", "source", "company", "title", "location", "salary", "posted", "snippet"]


def write_tsv(tsv: Path, jsonl: Path) -> None:
    """Compact triage view of the day's jsonl (one row per job) so the LLM can scan hundreds cheaply."""
    clean = lambda s: re.sub(r"[\t\n\r]+", " ", str(s or ""))  # noqa: E731
    rows = ["\t".join(TSV_COLS)]
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        j = json.loads(line)
        j["snippet"] = j["description"][:160]
        rows.append("\t".join(clean(j[c])[:200] for c in TSV_COLS))
    tsv.write_text("\n".join(rows) + "\n", encoding="utf-8")


# ---------- dashboard ----------
# Source of truth: frontmatter of applications/*/job.md (status, applied, reached, next_action_date…).
# Pipeline.base gives the live views; this writes the infographic panels Bases can't draw.

STAGES = ("screen", "interview", "offer")          # progress after sending, in order
SENT_PLUS = {"sent", "rejected", "ghosted", "withdrawn", *STAGES}
OPEN = {"sent", *STAGES}
OUTCOME_NODE = {"rejected": "Rejected", "ghosted": "Ghosted", "withdrawn": "Withdrawn"}


def read_frontmatter(path: Path) -> dict[str, str]:
    """Top-level scalar keys of a note's YAML frontmatter (list items and nested keys are skipped)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return {}
    out = {}
    for line in lines[1:]:
        if line == "---":
            break
        m = re.match(r"([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            out[m[1]] = m[2].strip().strip("\"'")
    return out


def _stamp_applied(path: Path, day: str) -> None:
    text = path.read_text(encoding="utf-8")
    end = text.index("\n---", 3)
    path.write_text(f"{text[:end]}\napplied: {day}{text[end:]}", encoding="utf-8")


def load_apps(apps: Path) -> tuple[list[dict], list[Path]]:
    """Read every application's frontmatter. A sent+ application with no `applied` key gets it stamped
    from the note's mtime (the kanban drag that moved it). `applied: unknown` is left alone."""
    rows, stamped = [], []
    for note in sorted(apps.glob("*/job.md")):
        fm = read_frontmatter(note)
        if fm.get("status") in SENT_PLUS and "applied" not in fm:
            day = dt.date.fromtimestamp(note.stat().st_mtime).isoformat()
            _stamp_applied(note, day)
            fm["applied"] = day
            stamped.append(note)
        rows.append({**fm, "dir": note.parent.name})
    return rows, stamped


def _date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _rank(row: dict) -> int:
    """Furthest stage reached: 0 none, 1 screen, 2 interview, 3 offer (from `reached` or the status)."""
    return max((STAGES.index(v) + 1 for v in (row.get("reached"), row.get("status")) if v in STAGES), default=0)


def metrics(rows: list[dict], today: dt.date, deadline: dt.date) -> dict:
    sent = [r for r in rows if r.get("status") in SENT_PLUS]
    due = lambda r: (d := _date(r.get("next_action_date"))) is not None and d <= today
    return {
        "sent": len(sent),
        "skipped": sum(r.get("status") == "skipped" for r in rows),
        "in_review": sum(r.get("status") == "drafted" for r in rows),
        "screen_plus": sum(_rank(r) >= 1 for r in sent),
        "interview_plus": sum(_rank(r) >= 2 for r in sent),
        "offers": sum(_rank(r) >= 3 for r in sent),
        "replied": sum(_rank(r) >= 1 or r.get("status") == "rejected" for r in sent),
        "active": sum(r.get("status") in OPEN for r in rows),
        "days_left": (deadline - today).days,
        "followups": [r for r in rows if r.get("status") in OPEN and due(r)],
        "stale_drafts": [r for r in rows if r.get("status") == "drafted"
                         and (d := _date(r["dir"])) and (today - d).days > 2],
        "ghost_candidates": [r for r in rows if r.get("status") == "sent"
                             and (d := _date(r.get("applied"))) and (today - d).days >= 21],
    }


def by_date(rows: list[dict], start: dt.date, today: dt.date, per_week: int):
    """Daily sent counts from `start` to `today`, their running total, and the target-pace total."""
    span = [start + dt.timedelta(n) for n in range((today - start).days + 1)]
    sent_days = [_date(r.get("applied")) for r in rows if r.get("status") in SENT_PLUS]
    daily = [sent_days.count(d) for d in span]
    cumulative = [sum(daily[: i + 1]) for i in range(len(daily))]
    pace = [round(per_week / 7 * (i + 1), 1) for i in range(len(span))]
    return [d.strftime("%m-%d") for d in span], daily, cumulative, pace


def sankey(rows: list[dict]) -> list[tuple[str, str, int]]:
    """Flows Applications → Sent → furthest stage → outcome, aggregated per edge."""
    counts: dict[tuple[str, str], int] = {}
    for r in rows:
        status = r.get("status")
        if status in SENT_PLUS:
            path = ["Applications", "Sent"] + [s.title() for s in STAGES[: _rank(r)]]
            leaf = OUTCOME_NODE.get(status) or ("Awaiting reply" if status == "sent"
                                                else None if status == "offer" else "In process")
        else:
            path, leaf = ["Applications"], {"skipped": "Skipped", "drafted": "In review"}.get(status, "Other")
        if leaf:
            path.append(leaf)
        for edge in zip(path, path[1:]):
            counts[edge] = counts.get(edge, 0) + 1
    return [(s, t, n) for (s, t), n in counts.items()]


def _pct(part: int, whole: int) -> str:
    return f"{part} ({round(100 * part / whole)}%)" if whole else str(part)


def _link(r: dict) -> str:
    return f"[{r.get('company', r['dir'])}](applications/{r['dir']}/job.md)"


def render_dashboard(rows: list[dict], today: dt.date, goal: dict) -> str:
    start, deadline, per_week = goal["start"], goal["deadline"], goal["per_week"]
    m = metrics(rows, today, deadline)
    days, daily, cumulative, pace = by_date(rows, start, today, per_week)
    before = sum(1 for r in rows if r.get("status") in SENT_PLUS
                 and ((d := _date(r.get("applied"))) is None or d < start))
    top = max(cumulative + pace + daily + [1])
    q = lambda xs: "[" + ", ".join(f'"{x}"' for x in xs) + "]"
    nums = lambda xs: "[" + ", ".join(str(x) for x in xs) + "]"
    flows = "\n".join(f"{s},{t},{n}" for s, t, n in sankey(rows))
    todo = [f"- {_link(r)}: {r.get('next_action', 'follow up')} (due {r['next_action_date']})"
            for r in m["followups"]]
    todo += [f"- {_link(r)}: silent since {r['applied']} → mark `ghosted` or follow up" for r in m["ghost_candidates"]]
    todo += [f"- {_link(r)}: draft waiting since {r['dir'][:10]} → send or skip" for r in m["stale_drafts"]]
    return f"""---
type: career
updated: {today.isoformat()}
tags:
  - career
  - job-hunt
---
# Job hunt dashboard

> Generated by `jobhunt.py dashboard` (daily run and `/jobs status`): don't edit, change the application notes instead. As of **{today.isoformat()}**. Live views (Obsidian): [Pipeline](Pipeline.base).

| Sent | Any reply | Screen+ | Interview+ | Offers | Active | In review | Skipped | Days to {deadline.isoformat()} |
|---|---|---|---|---|---|---|---|---|
| **{m['sent']}** | {_pct(m['replied'], m['sent'])} | {_pct(m['screen_plus'], m['sent'])} | {_pct(m['interview_plus'], m['sent'])} | {m['offers']} | {m['active']} | {m['in_review']} | {m['skipped']} | {m['days_left']} |

## Applications sent by date
Bars: sent per day · line 1: cumulative · line 2: target pace ({per_week}/week). Counted from {start.isoformat()}; {before} earlier or undated sends are in the totals above only.

```mermaid
xychart-beta
  title "Sent: {cumulative[-1] if cumulative else 0} vs pace {pace[-1] if pace else 0}"
  x-axis {q(days)}
  y-axis "Applications" 0 --> {int(top) + 1}
  bar {nums(daily)}
  line {nums(cumulative)}
  line {nums(pace)}
```

## Where applications end up
```mermaid
sankey-beta
{flows}
```

## Needs action
{chr(10).join(todo) if todo else "Nothing due."}

## Board
![[Pipeline.base#Kanban]]
"""


def dashboard(apps: Path, out: Path, today: dt.date, goal: dict) -> list[Path]:
    rows, stamped = load_apps(apps)
    out.write_text(render_dashboard(rows, today, goal), encoding="utf-8")
    return stamped


# ---------- rendering ----------

def pending_renders(apps: Path) -> list[Path]:
    out = []
    for html_file in sorted(apps.glob("*/*.html")):
        if html_file.stem not in ("cv", "cover-letter"):
            continue
        pdf = html_file.with_suffix(".pdf")
        if not pdf.exists() or pdf.stat().st_mtime < html_file.stat().st_mtime:
            out.append(html_file)
    return out


def chrome_cmd(src: Path, pdf: Path, profile: Path) -> list[str]:
    # A throwaway profile keeps headless Chrome off the user's running profile (shared one = hang on exit).
    return [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--no-pdf-header-footer", f"--user-data-dir={profile}", f"--print-to-pdf={pdf}",
            src.resolve().as_uri() if src.exists() else f"file://{src}"]


def _run_chrome(cmd: list[str], timeout: int) -> None:
    subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)


def render(apps: Path, runner=_run_chrome) -> tuple[list[Path], list[Path]]:
    """Render pending HTML → PDF. A PDF that was written counts even if Chrome then hangs; one failure
    never stops the rest. Returns (rendered, failed)."""
    import tempfile
    done, failed = [], []
    with tempfile.TemporaryDirectory(prefix="jobhunt-chrome-") as profile:
        for src in pending_renders(apps):
            pdf = src.with_suffix(".pdf")
            started = time.time()
            try:
                runner(chrome_cmd(src, pdf, Path(profile)), 60)
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
                pass
            fresh = pdf.exists() and pdf.stat().st_size > 0 and pdf.stat().st_mtime >= started - 1
            (done if fresh else failed).append(pdf)
    return done, failed


# ---------- CLI ----------

class ConfigError(Exception):
    pass


def load_config(path: Path) -> dict:
    """Read and validate the config: {hunt_dir: Path, profile: [glob], goal: {start, deadline, per_week}}.
    Profile globs are relative to hunt_dir."""
    if not path.exists():
        raise ConfigError(f"config {path} not found: run `/jobs setup` or `jobhunt.py init <hunt_dir>`")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    if not isinstance(raw.get("hunt_dir"), str):
        raise ConfigError(f"{path}: hunt_dir must be a path string")
    profile = raw.get("profile", ["profile/*.md"])
    if not (isinstance(profile, list) and profile and all(isinstance(p, str) for p in profile)):
        raise ConfigError(f"{path}: profile must be a non-empty list of path globs")
    goal = raw.get("goal")
    if not isinstance(goal, dict):
        raise ConfigError(f"{path}: missing [goal] table (start, deadline, per_week)")
    for key, kind in (("start", dt.date), ("deadline", dt.date), ("per_week", int)):
        if not isinstance(goal.get(key), kind) or isinstance(goal.get(key), (dt.datetime, bool)):
            raise ConfigError(f"{path}: goal.{key} must be {'a date like 2026-12-31' if kind is dt.date else 'an integer'}")
    return {"hunt_dir": Path(raw["hunt_dir"]).expanduser(), "profile": profile,
            "goal": {k: goal[k] for k in ("start", "deadline", "per_week")}}


def where(c: dict) -> list[Path]:
    """The hunt dir, then each directory outside it that holds profile files (headless runs must read them)."""
    hunt = c["hunt_dir"]
    dirs = [hunt]
    for pattern in c["profile"]:
        d = Path(os.path.normpath(hunt / pattern)).parent
        if d not in dirs and not d.is_relative_to(hunt):
            dirs.append(d)
    return dirs


def init(hunt: Path, config: Path, today: dt.date, templates: Path = TEMPLATES) -> list[Path]:
    """Copy templates into the hunt dir without overwriting, create the working folders, and write the
    config unless one exists. Returns the files created."""
    created = []
    for src in sorted(p for p in templates.rglob("*") if p.is_file() and p.name != ".DS_Store"):
        dst = hunt / src.relative_to(templates)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            created.append(dst)
    for d in ("applications", "daily", "market"):
        (hunt / d).mkdir(parents=True, exist_ok=True)
    if not config.exists():
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(f"""# jobhunt config, see SETUP.md. Paths may use ~.
hunt_dir = "{hunt}"
# Profile notes the agent reads for facts (globs, relative to hunt_dir).
profile = ["profile/*.md"]

[goal]
start = {today.isoformat()}        # first day counted on the dashboard chart
deadline = {(today + dt.timedelta(90)).isoformat()}     # "days left" on the dashboard and in weekly reviews
per_week = 10              # target applications sent per week (the pace line)
""", encoding="utf-8")
        created.append(config)
    return created


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=CONFIG_FILE, help="default: %(default)s")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("hunt_dir", type=Path)
    sub.add_parser("where")
    f = sub.add_parser("fetch")
    f.add_argument("--sources", type=Path, help="default: <hunt_dir>/sources.toml")
    f.add_argument("--state", type=Path, default=DEFAULT_STATE)
    f.add_argument("--date", type=dt.date.fromisoformat, default=dt.date.today())
    r = sub.add_parser("render")
    r.add_argument("--apps", type=Path, help="default: <hunt_dir>/applications")
    d = sub.add_parser("dashboard")
    d.add_argument("--apps", type=Path, help="default: <hunt_dir>/applications")
    d.add_argument("--out", type=Path, help="default: <hunt_dir>/dashboard.md")
    d.add_argument("--date", type=dt.date.fromisoformat, default=dt.date.today())
    a = ap.parse_args(argv)

    if a.cmd == "init":
        hunt = a.hunt_dir.expanduser().resolve()
        for path in init(hunt, a.config, dt.date.today()):
            print(f"created {path}")
        print(f"hunt dir: {hunt}\nconfig:   {a.config}")
        return 0

    try:
        c = load_config(a.config)
    except ConfigError as e:
        print(f"jobhunt: {e}", file=sys.stderr)
        return 2
    hunt = c["hunt_dir"]

    if a.cmd == "where":
        print("\n".join(str(p) for p in where(c)))
        return 0

    if a.cmd == "dashboard":
        out = a.out or hunt / "dashboard.md"
        for note in dashboard(a.apps or hunt / "applications", out, a.date, c["goal"]):
            print(f"stamped applied date from mtime: {note}")
        print(f"wrote {out}")
        return 0

    if a.cmd == "fetch":
        cfg = tomllib.loads((a.sources or hunt / "sources.toml").read_text(encoding="utf-8"))
        s = run(cfg, a.state, a.date, http_get)
        for name, st in s["sources"].items():
            extra = f" ERROR {st['error']}" if st["error"] else f" rejected={st['rejected']}"
            print(f"{name:14} fetched={st['fetched']:4} new={st['kept']:3}{extra}")
        print(f"NEW {s['new']} → {a.state / 'new' / (a.date.isoformat() + '.jsonl')}")
        return 0

    if not Path(CHROME).exists():
        print(f"jobhunt: Google Chrome not found at {CHROME}; install it to render PDFs", file=sys.stderr)
        return 1
    done, failed = render(a.apps or hunt / "applications")
    for pdf in done:
        print(f"rendered {pdf}")
    for pdf in failed:
        print(f"FAILED {pdf}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
