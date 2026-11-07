#!/usr/bin/env python3
# Tests for jobhunt.py. Run: python3 -B -m unittest discover -s ~/.claude/skills/jobs
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

import jobhunt as jh  # noqa: E402

TODAY = dt.date(2026, 11, 1)

CFG = {
    "max_age_days": 14,
    "max_age_days_ats": 45,
    "salary_floor_usd_year": 36000,
    "filters": {
        "title_role": r"engineer|developer|cto|devops|sre|architect|разработчик|тимлид",
        "title_exclude": r"junior|intern|designer|sales|account exec|ios|android",
        "stack": r"php|drupal|wordpress|symfony|node|typescript|nestjs|postgres|backend|devops|platform",
        "location_exclude": r"\bus only\b|united states only|u\.s\. based",
        "location_allow": r"remote|anywhere|worldwide|europe|emea|netherlands|amsterdam",
        "text_allow": r"relocat|visa sponsor",
    },
    "boards": {
        "remoteok": True,
        "himalayas_queries": ["php"],
        "wwr_categories": ["remote-back-end-programming-jobs"],
        "remotive_categories": ["software-dev"],
        "workingnomads": True,
        "jobicy_industries": ["dev"],
        "hn": True,
        "habr_queries": ["php"],
    },
    "ats": {"greenhouse": ["acme"], "ashby": ["beta"], "lever": ["gamma"]},
}


def job(**kw):
    base = {
        "id": "x:1", "source": "x", "kind": "board", "title": "Senior Backend Engineer",
        "company": "Acme", "location": "Remote", "url": "https://e.x/1",
        "posted": "2026-10-30", "salary": "", "salary_min_usd": None, "salary_max_usd": None,
        "tags": ["php"], "description": "We use PHP and Postgres.",
    }
    base.update(kw)
    return base


class FakeGet:
    """Maps URL substrings to payloads; records calls."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        for frag, payload in self.routes.items():
            if frag in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        raise AssertionError(f"unexpected url {url}")


RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Dropbox: Backend Product Software Engineer</title><region>Anywhere in the World</region>
<category>Back-End Programming</category><description>&lt;p&gt;We use &lt;b&gt;Node&lt;/b&gt;&lt;/p&gt;</description>
<pubDate>Sat, 31 Oct 2026 07:31:12 +0000</pubDate>
<guid>https://weworkremotely.com/remote-jobs/dropbox-1</guid><link>https://weworkremotely.com/remote-jobs/dropbox-1</link></item>
</channel></rss>"""

HABR = """<?xml version="1.0"?><rss><channel>
<item><title>Требуется «Senior PHP-разработчик»</title>
<description>Компания «IT_One» ищет специалиста. Можно удалённо. Требуемые навыки: #PHP, #Symfony.</description>
<author>IT_One</author><pubDate>Sat, 31 Oct 2026 07:28:03 +0300</pubDate>
<link>https://career.habr.com/vacancies/1000168718</link><guid>1000168718</guid></item>
</channel></rss>""".encode()


class TestNormalizers(unittest.TestCase):
    def test_remoteok_skips_legal_row_and_reads_salary(self):
        get = FakeGet({"remoteok.com": [
            {"legal": "terms"},
            {"id": "11", "date": "2026-10-31T00:00:04+00:00", "company": "Acme", "position": "Senior PHP Developer",
             "tags": ["php"], "location": "Worldwide", "salary_min": 60000, "salary_max": 80000,
             "url": "https://remoteOK.com/remote-jobs/11", "description": "<p>PHP</p>"},
        ]})
        jobs = jh.src_remoteok(CFG, get)
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j["id"], "remoteok:11")
        self.assertEqual(j["posted"], "2026-10-31")
        self.assertEqual((j["salary_min_usd"], j["salary_max_usd"]), (60000, 80000))
        self.assertEqual(j["description"], "PHP")

    def test_remoteok_zero_salary_is_unknown(self):
        get = FakeGet({"remoteok.com": [{"legal": "t"}, {"id": "2", "date": "2026-10-31T00:00:00+00:00",
                       "company": "A", "position": "Dev", "salary_min": 0, "salary_max": 0, "url": "u"}]})
        j = jh.src_remoteok(CFG, get)[0]
        self.assertIsNone(j["salary_max_usd"])

    def test_himalayas_epoch_and_currency(self):
        get = FakeGet({"himalayas.app": {"jobs": [
            {"title": "Senior Backend Engineer", "companyName": "Nerdio", "locationRestrictions": ["Germany", "Poland"],
             "minSalary": 90000, "maxSalary": 120000, "currency": "EUR", "categories": ["Backend"],
             "applicationLink": "https://himalayas.app/x?utm_source=api", "guid": "https://himalayas.app/companies/nerdio/jobs/x",
             "pubDate": 1793485525, "excerpt": "Node and Postgres"}]}})
        j = jh.src_himalayas(CFG, get)[0]
        self.assertEqual(j["id"], "himalayas:https://himalayas.app/companies/nerdio/jobs/x")
        self.assertEqual(j["location"], "Germany, Poland")
        self.assertIsNone(j["salary_max_usd"], "non-USD salary must not be compared against the USD floor")
        self.assertIn("EUR", j["salary"])
        self.assertTrue(j["posted"].startswith("2026-"))

    def test_himalayas_empty_restrictions_means_worldwide(self):
        get = FakeGet({"himalayas.app": {"jobs": [{"title": "Dev", "companyName": "A", "locationRestrictions": [],
                                                    "guid": "g", "pubDate": 1793485525}]}})
        self.assertEqual(jh.src_himalayas(CFG, get)[0]["location"], "Worldwide")

    def test_wwr_rss_splits_company_from_title(self):
        get = FakeGet({"weworkremotely.com": RSS})
        j = jh.src_wwr(CFG, get)[0]
        self.assertEqual((j["company"], j["title"]), ("Dropbox", "Backend Product Software Engineer"))
        self.assertEqual(j["location"], "Anywhere in the World")
        self.assertEqual(j["posted"], "2026-10-31")
        self.assertEqual(j["description"], "We use Node")

    def test_habr_strips_prefix_and_uses_author(self):
        get = FakeGet({"career.habr.com": HABR})
        j = jh.src_habr(CFG, get)[0]
        self.assertEqual((j["title"], j["company"]), ("Senior PHP-разработчик", "IT_One"))
        self.assertEqual(j["id"], "habr:1000168718")
        self.assertIn("удалённо", j["location"])

    def test_habr_title_with_city_suffix(self):
        raw = HABR.replace("«Senior PHP-разработчик»".encode(), "«Team Lead PHP» (Москва)".encode())
        j = jh.src_habr(CFG, FakeGet({"career.habr.com": raw}))[0]
        self.assertEqual(j["title"], "Team Lead PHP (Москва)")

    def test_mojibake_is_repaired(self):
        self.assertEqual(jh.mk("x", "board", 1, company="Sothebyâ\u0080\u0099s")["company"], "Sotheby’s")
        self.assertEqual(jh.mk("x", "board", 1, company="Café")["company"], "Café")

    def test_hn_takes_latest_whos_hiring_top_level_comments_only(self):
        get = FakeGet({
            "author_whoishiring": {"hits": [
                {"title": "Ask HN: Who wants to be hired? (October 2026)", "objectID": "9"},
                {"title": "Ask HN: Who is hiring? (October 2026)", "objectID": "100", "created_at": "2026-10-01T15:00:00Z"},
            ]},
            "story_100": {"nbPages": 1, "hits": [
                {"objectID": "1", "parent_id": 100, "created_at": "2026-10-02T10:00:00Z",
                 "comment_text": "Acme | Senior Backend Engineer (PHP) | REMOTE (EU) | $90k<p>We build things."},
                {"objectID": "2", "parent_id": 1, "created_at": "2026-10-02T11:00:00Z", "comment_text": "reply"},
            ]},
        })
        jobs = jh.src_hn(CFG, get)
        self.assertEqual([j["id"] for j in jobs], ["hn:1"])
        self.assertEqual(jobs[0]["company"], "Acme")
        self.assertIn("Senior Backend Engineer", jobs[0]["title"])
        self.assertIn("We build things.", jobs[0]["description"])

    def test_greenhouse_unescapes_content(self):
        get = FakeGet({"boards-api.greenhouse.io": {"jobs": [
            {"id": 5, "title": "Senior Backend Engineer", "location": {"name": "Remote, EMEA"},
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/5", "first_published": "2026-10-20T10:00:00-04:00",
             "updated_at": "2026-10-28T10:00:00-04:00", "content": "&lt;p&gt;PHP &amp;amp; Go&lt;/p&gt;"}]}})
        j = jh.src_greenhouse(CFG, get)[0]
        self.assertEqual(j["id"], "greenhouse:acme:5")
        self.assertEqual(j["company"], "acme")
        self.assertEqual(j["kind"], "ats")
        self.assertEqual(j["description"], "PHP & Go")
        self.assertEqual(j["posted"], "2026-10-20")

    def test_ashby_and_lever(self):
        get = FakeGet({
            "api.ashbyhq.com": {"jobs": [{"id": "u1", "title": "Senior Fullstack Engineer", "location": "Europe",
                                          "isRemote": True, "jobUrl": "https://jobs.ashbyhq.com/beta/u1",
                                          "publishedAt": "2026-10-25T20:13:45.158+00:00", "descriptionPlain": "TypeScript",
                                          "compensation": {"compensationTierSummary": "€80K – €100K"}}]},
            "api.lever.co": [{"id": "l1", "text": "Platform Engineer", "categories": {"location": "Remote - Europe"},
                              "hostedUrl": "https://jobs.lever.co/gamma/l1", "createdAt": 1793000000000,
                              "descriptionPlain": "Kubernetes", "workplaceType": "remote"}],
        })
        a = jh.src_ashby(CFG, get)[0]
        self.assertEqual((a["id"], a["location"], a["salary"]), ("ashby:beta:u1", "Europe (remote)", "€80K – €100K"))
        lv = jh.src_lever(CFG, get)[0]
        self.assertEqual((lv["id"], lv["title"], lv["location"]), ("lever:gamma:l1", "Platform Engineer", "Remote - Europe"))


class TestFilter(unittest.TestCase):
    def reason(self, j):
        return jh.reject_reason(j, CFG, TODAY)

    def test_keeps_good_board_job(self):
        self.assertIsNone(self.reason(job()))

    def test_title_must_be_a_role_and_not_excluded(self):
        self.assertEqual(self.reason(job(title="Account Manager")), "title")
        self.assertEqual(self.reason(job(title="Junior PHP Developer")), "title")

    def test_stack_checked_over_title_tags_description(self):
        self.assertEqual(self.reason(job(title="Senior Software Engineer", tags=[], description="Swift and UIKit")),
                         "stack")
        self.assertIsNone(self.reason(job(title="Senior Drupal Developer", tags=[], description="")))

    def test_location_exclude(self):
        self.assertEqual(self.reason(job(location="US Only")), "location")

    def test_ats_needs_allowed_location_or_relocation_in_text(self):
        onsite = job(kind="ats", location="San Francisco, CA", description="PHP")
        self.assertEqual(self.reason(onsite), "location")
        self.assertIsNone(self.reason(job(kind="ats", location="Amsterdam", description="PHP")))
        self.assertIsNone(self.reason(job(kind="ats", location="Zurich", description="PHP. We offer visa sponsorship.")))
        boilerplate = job(kind="ats", location="New York, NY", description="PHP. Some teams are remote-friendly.")
        self.assertEqual(self.reason(boilerplate), "location", "'remote' in the description alone is not enough")

    def test_age_limits_differ_for_boards_and_ats(self):
        self.assertEqual(self.reason(job(posted="2026-10-01")), "age")
        self.assertIsNone(self.reason(job(kind="ats", location="Remote", posted="2026-10-01")))
        self.assertEqual(self.reason(job(kind="ats", location="Remote", posted="2026-08-01")), "age")
        self.assertIsNone(self.reason(job(kind="hn", location="Acme | REMOTE", posted="2026-10-02")),
                          "monthly HN thread uses the long window")
        self.assertIsNone(self.reason(job(posted="")), "unknown date is kept")

    def test_salary_floor_only_on_known_annual_usd(self):
        self.assertEqual(self.reason(job(salary_max_usd=30000)), "salary")
        self.assertIsNone(self.reason(job(salary_max_usd=40000)))
        self.assertIsNone(self.reason(job(salary_max_usd=4000)), "small numbers look monthly: ambiguous, keep")


class TestRun(unittest.TestCase):
    def test_run_dedupes_across_sources_and_runs_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            a = job(id="remoteok:1", source="remoteok")
            b = job(id="wwr:9", source="wwr", company="ACME ", title="Senior  Backend Engineer")
            bad = job(id="remoteok:2", title="Sales Lead")
            sources = {"remoteok": lambda c, g: [a, bad], "wwr": lambda c, g: [b],
                       "broken": lambda c, g: (_ for _ in ()).throw(OSError("boom"))}
            summary = jh.run(CFG, state, TODAY, get=None, sources=sources)
            self.assertEqual(summary["new"], 1)
            self.assertEqual(summary["sources"]["broken"]["error"], "OSError: boom")
            self.assertEqual(summary["sources"]["remoteok"]["rejected"], {"title": 1})
            out = (state / "new" / "2026-11-01.jsonl").read_text().splitlines()
            self.assertEqual([json.loads(x)["id"] for x in out], ["remoteok:1"])
            tsv = (state / "new" / "2026-11-01.tsv").read_text().splitlines()
            self.assertEqual(tsv[0].split("\t")[:3], ["id", "source", "company"])
            self.assertEqual(tsv[1].split("\t")[0], "remoteok:1")
            self.assertEqual(len(tsv), 2)
            again = jh.run(CFG, state, TODAY + dt.timedelta(days=1), get=None, sources=sources)
            self.assertEqual(again["new"], 0)
            runs = (state / "runs.jsonl").read_text().splitlines()
            self.assertEqual(len(runs), 2)

    def test_seen_entries_expire(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            sources = {"remoteok": lambda c, g: [job(posted="")]}
            jh.run(CFG, state, TODAY, get=None, sources=sources)
            later = jh.run(CFG, state, TODAY + dt.timedelta(days=jh.SEEN_TTL_DAYS + 1), get=None, sources=sources)
            self.assertEqual(later["new"], 1)

    def test_enabled_sources_follow_config(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["boards"]["remoteok"] = False
        cfg["boards"]["habr_queries"] = []
        cfg["ats"]["lever"] = []
        names = set(jh.enabled_sources(cfg))
        self.assertNotIn("remoteok", names)
        self.assertNotIn("habr", names)
        self.assertNotIn("lever", names)
        self.assertIn("greenhouse", names)


class TestRender(unittest.TestCase):
    def test_pending_renders_only_missing_or_stale_pdfs(self):
        with tempfile.TemporaryDirectory() as d:
            app = Path(d) / "2026-11-01-acme-backend"
            app.mkdir()
            (app / "cv.html").write_text("<p>cv</p>")
            (app / "cover-letter.html").write_text("<p>cl</p>")
            (app / "cover-letter.pdf").write_text("pdf")
            os.utime(app / "cover-letter.html", (1, 1))
            self.assertEqual(jh.pending_renders(Path(d)), [app / "cv.html"])

    def test_chrome_command(self):
        cmd = jh.chrome_cmd(Path("/a/cv.html"), Path("/a/cv.pdf"), Path("/tmp/prof"))
        self.assertIn("--headless=new", cmd)
        self.assertIn("--no-pdf-header-footer", cmd)
        self.assertIn("--print-to-pdf=/a/cv.pdf", cmd)
        self.assertIn("--user-data-dir=/tmp/prof", cmd, "own profile: never contend with the user's running Chrome")
        self.assertEqual(cmd[-1], "file:///a/cv.html")

    def test_render_survives_hang_and_failure(self):
        with tempfile.TemporaryDirectory() as d:
            apps = Path(d)
            for name in ("a", "b", "c"):
                (apps / name).mkdir()
                (apps / name / "cv.html").write_text("<p>x</p>")

            def runner(cmd, timeout):
                pdf = Path(next(c for c in cmd if c.startswith("--print-to-pdf=")).split("=", 1)[1])
                if "/a/" in str(pdf):      # writes the PDF, then hangs
                    pdf.write_bytes(b"%PDF-1.4 ok")
                    raise jh.subprocess.TimeoutExpired(cmd, timeout)
                if "/b/" in str(pdf):      # crashes without output
                    raise jh.subprocess.CalledProcessError(1, cmd)
                pdf.write_bytes(b"%PDF-1.4 ok")

            done, failed = jh.render(apps, runner=runner)
            self.assertEqual(sorted(p.parent.name for p in done), ["a", "c"])
            self.assertEqual([p.parent.name for p in failed], ["b"])


def app_note(apps: Path, name: str, **fm) -> Path:
    d = apps / name
    d.mkdir(parents=True)
    lines = ["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["---", "# body", ""]
    (d / "job.md").write_text("\n".join(lines), encoding="utf-8")
    return d / "job.md"


DASH_TODAY = dt.date(2026, 11, 3)
GOAL = {"start": dt.date(2026, 11, 1), "deadline": dt.date(2026, 12, 31), "per_week": 15}


class TestDashboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.apps = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_frontmatter_scalars_quotes_and_lists(self):
        p = app_note(self.apps, "a", company='"Acme, Inc"', score=80, tags="", applied="2026-11-01")
        p.write_text(p.read_text().replace("tags: \n", "tags:\n  - x\n"))
        fm = jh.read_frontmatter(p)
        self.assertEqual(fm["company"], "Acme, Inc")
        self.assertEqual(fm["score"], "80")
        self.assertEqual(fm["applied"], "2026-11-01")
        self.assertNotIn("  - x", fm.values())

    def test_load_stamps_missing_applied_from_mtime_only_for_sent_plus(self):
        sent = app_note(self.apps, "2026-11-01-a", company="A", status="sent")
        drafted = app_note(self.apps, "2026-11-01-b", company="B", status="drafted")
        unknown = app_note(self.apps, "2026-10-01-c", company="C", status="rejected", applied="unknown")
        ts = dt.datetime(2026, 11, 2, 12).timestamp()
        os.utime(sent, (ts, ts))
        rows, stamped = jh.load_apps(self.apps)
        self.assertEqual(stamped, [sent])
        self.assertIn("applied: 2026-11-02", sent.read_text())
        self.assertNotIn("applied", drafted.read_text())
        self.assertIn("applied: unknown", unknown.read_text())
        self.assertEqual({r["company"]: r.get("applied") for r in rows}["A"], "2026-11-02")
        self.assertEqual(rows[1]["dir"], "2026-11-01-a")

    def _fixture(self):
        app_note(self.apps, "2026-11-01-a", company="A", status="sent", applied="2026-11-01",
                 next_action_date="2026-11-03")
        app_note(self.apps, "2026-11-01-b", company="B", status="rejected", applied="2026-11-01")
        app_note(self.apps, "2026-11-02-c", company="C", status="interview", reached="interview",
                 applied="2026-11-03")
        app_note(self.apps, "2026-10-20-d", company="D", status="rejected", reached="interview",
                 applied="unknown")
        app_note(self.apps, "2026-09-14-e", company="E", status="ghosted", applied="2026-09-14")
        app_note(self.apps, "2026-11-02-f", company="F", status="skipped")
        app_note(self.apps, "2026-10-30-g", company="G", status="drafted")
        app_note(self.apps, "2026-11-03-h", company="H", status="drafted")
        return jh.load_apps(self.apps)[0]

    def test_metrics(self):
        m = jh.metrics(self._fixture(), DASH_TODAY, GOAL["deadline"])
        self.assertEqual(m["sent"], 5)
        self.assertEqual(m["skipped"], 1)
        self.assertEqual(m["in_review"], 2)
        self.assertEqual(m["screen_plus"], 2)
        self.assertEqual(m["interview_plus"], 2)
        self.assertEqual(m["active"], 2)
        self.assertEqual(m["days_left"], 58)
        self.assertEqual([r["company"] for r in m["followups"]], ["A"])
        self.assertEqual([r["company"] for r in m["stale_drafts"]], ["G"])
        self.assertEqual(m["ghost_candidates"], [])

    def test_ghost_candidate_after_21_days_silent(self):
        app_note(self.apps, "2026-10-01-z", company="Z", status="sent", applied="2026-10-10")
        m = jh.metrics(jh.load_apps(self.apps)[0], DASH_TODAY, GOAL["deadline"])
        self.assertEqual([r["company"] for r in m["ghost_candidates"]], ["Z"])

    def test_by_date_counts_from_hunt_start_with_cumulative_and_pace(self):
        days, daily, cumulative, pace = jh.by_date(self._fixture(), dt.date(2026, 11, 1), DASH_TODAY, 15)
        self.assertEqual(days, ["11-01", "11-02", "11-03"])
        self.assertEqual(daily, [2, 0, 1])
        self.assertEqual(cumulative, [2, 2, 3])
        self.assertEqual(pace, [2.1, 4.3, 6.4])

    def test_sankey_follows_reached_stage_then_outcome(self):
        flows = {(s, t): n for s, t, n in jh.sankey(self._fixture())}
        self.assertEqual(flows[("Applications", "Sent")], 5)
        self.assertEqual(flows[("Applications", "Skipped")], 1)
        self.assertEqual(flows[("Applications", "In review")], 2)
        self.assertEqual(flows[("Sent", "Screen")], 2)
        self.assertEqual(flows[("Screen", "Interview")], 2)
        self.assertEqual(flows[("Interview", "Rejected")], 1)
        self.assertEqual(flows[("Interview", "In process")], 1)
        self.assertEqual(flows[("Sent", "Rejected")], 1)
        self.assertEqual(flows[("Sent", "Ghosted")], 1)
        self.assertEqual(flows[("Sent", "Awaiting reply")], 1)

    def test_render_dashboard_has_charts_and_embeds(self):
        md = jh.render_dashboard(self._fixture(), DASH_TODAY, GOAL)
        self.assertIn("xychart-beta", md)
        self.assertIn("bar [2, 0, 1]", md)
        self.assertIn("sankey-beta", md)
        self.assertIn("Applications,Sent,5", md)
        self.assertIn("![[Pipeline.base#Kanban]]", md)
        self.assertIn("[A](applications/2026-11-01-a/job.md)", md)
        self.assertIn("Days to 2026-12-31", md)
        self.assertIn("pace (15/week)", md)


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "config.toml"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, body: str) -> Path:
        self.cfg.write_text(body, encoding="utf-8")
        return self.cfg

    def test_load_resolves_paths_and_reads_goal(self):
        hunt = self.root / "hunt"
        self.write(f'hunt_dir = "{hunt}"\nprofile = ["../me.md", "profile/*.md"]\n'
                   "[goal]\nstart = 2026-11-01\ndeadline = 2026-12-31\nper_week = 15\n")
        c = jh.load_config(self.cfg)
        self.assertEqual(c["hunt_dir"], hunt)
        self.assertEqual(c["profile"], ["../me.md", "profile/*.md"])
        self.assertEqual(c["goal"], GOAL)

    def test_tilde_and_default_profile(self):
        self.write('hunt_dir = "~/hunt"\n[goal]\nstart = 2026-11-01\ndeadline = 2026-12-31\nper_week = 5\n')
        c = jh.load_config(self.cfg)
        self.assertEqual(c["hunt_dir"], Path.home() / "hunt")
        self.assertEqual(c["profile"], ["profile/*.md"])

    def test_invalid_config_names_the_problem(self):
        with self.assertRaisesRegex(jh.ConfigError, "not found.*jobs setup"):
            jh.load_config(self.root / "missing.toml")
        self.write('hunt_dir = "/x"\n')
        with self.assertRaisesRegex(jh.ConfigError, r"\[goal\]"):
            jh.load_config(self.cfg)
        self.write('hunt_dir = "/x"\n[goal]\nstart = "soon"\ndeadline = 2026-12-31\nper_week = 5\n')
        with self.assertRaisesRegex(jh.ConfigError, "goal.start"):
            jh.load_config(self.cfg)

    def test_where_lists_hunt_dir_then_outside_profile_dirs(self):
        hunt = self.root / "vault" / "hunt"
        (hunt / "profile").mkdir(parents=True)
        (self.root / "vault" / "roles").mkdir()
        c = {"hunt_dir": hunt, "profile": ["../me.md", "../roles/*.md", "profile/*.md"], "goal": GOAL}
        self.assertEqual(jh.where(c), [hunt, self.root / "vault", self.root / "vault" / "roles"])

    def test_init_copies_templates_without_overwriting_and_writes_config(self):
        tpl = self.root / "tpl"
        (tpl / "profile").mkdir(parents=True)
        (tpl / "criteria.md").write_text("template")
        (tpl / "profile" / "profile.md").write_text("template")
        hunt = self.root / "hunt"
        hunt.mkdir()
        (hunt / "criteria.md").write_text("mine")
        created = jh.init(hunt, self.cfg, dt.date(2026, 11, 1), templates=tpl)
        self.assertEqual((hunt / "criteria.md").read_text(), "mine")
        self.assertEqual((hunt / "profile" / "profile.md").read_text(), "template")
        for d in ("applications", "daily", "market"):
            self.assertTrue((hunt / d).is_dir())
        self.assertIn(hunt / "profile" / "profile.md", created)
        self.assertNotIn(hunt / "criteria.md", created)
        c = jh.load_config(self.cfg)
        self.assertEqual(c["hunt_dir"], hunt)
        self.assertEqual(c["goal"]["deadline"], dt.date(2027, 1, 30))
        self.cfg.write_text(self.cfg.read_text().replace("per_week = 10", "per_week = 3"))
        jh.init(hunt, self.cfg, dt.date(2026, 11, 1), templates=tpl)
        self.assertEqual(jh.load_config(self.cfg)["goal"]["per_week"], 3)


if __name__ == "__main__":
    unittest.main()
