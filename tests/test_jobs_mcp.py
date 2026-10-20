#!/usr/bin/env python3
"""Oracle: mcp/jobs/server.py reads public ATS / gov.uk data and FAILS CLOSED.

    venv/bin/python tests/test_jobs_mcp.py

Hermetic: the module's one network seam (_fetch) is replaced by a fake that serves fixtures
by URL and records every call; the register cache lives in a temp dir. Fixtures are neutral
("example-co", "Acme"); no real company, candidate or target data.

Both directions, every tool:
  live posting → live=true            gone posting (404) → live=false
  absent from a listed-only board → live=null    unknown host → live=null, nothing fetched
  any host outside ALLOWED_HOSTS (redirect hops too) → refused, a loopback listener sees 0 hits
  match → rows                        no match → match_count 0 (and NOT an error)
  API/transport/shape failure → "error: ..."  — never live=false, never "no match"
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from astryx.security.sqlguard.estate import gate  # noqa: E402
gate("test_jobs_mcp", REPO, deps=("httpx", "mcp.server"), env=False)   # a committed-only tree (no venv): 77, not an import crash
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {str(detail)[:300]}")


tmp = tempfile.mkdtemp(prefix="jobs-oracle.")
os.environ["JOBS_CACHE_DIR"] = tmp
spec = importlib.util.spec_from_file_location("jobs_server", REPO / "mcp" / "jobs" / "server.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
S.CACHE_DIR = Path(tmp)

ROUTES: dict = {}
CALLS: list = []


def fake_fetch(url):
    CALLS.append(url)
    for prefix, resp in ROUTES.items():
        if url.startswith(prefix):
            if isinstance(resp, Exception):
                raise resp
            return resp
    raise AssertionError(f"unrouted URL in test: {url}")


S._fetch = fake_fetch


def route(**kv):
    ROUTES.clear()
    CALLS.clear()
    ROUTES.update(kv)


def J(obj):
    return 200, json.dumps(obj)


def is_err(s):
    return isinstance(s, str) and s.startswith("error:")


def parse(s):
    try:
        return json.loads(s)
    except Exception:
        return None


GH_API = "https://boards-api.greenhouse.io/v1/boards/example-co/jobs/123"
GH_URL = "https://job-boards.greenhouse.io/example-co/jobs/123"
GH_CONTENT = (
    "&lt;p&gt;We build things.&lt;/p&gt;"
    "&lt;h3&gt;You may be a good fit if you have&lt;/h3&gt;"
    "&lt;ul&gt;&lt;li&gt;&lt;p&gt;5+ years of Python&lt;/p&gt;&lt;/li&gt;"
    "&lt;li&gt;&lt;p&gt;SQL fluency&lt;/p&gt;&lt;/li&gt;&lt;/ul&gt;"
    "&lt;p&gt;Visa sponsorship: We do sponsor visas! Lunch is free.&lt;/p&gt;"
    "&lt;p&gt;Relocation support is available for this role.&lt;/p&gt;")
GH_JOB = {"id": 123, "title": "Data Scientist", "location": {"name": "London, UK"},
          "updated_at": "2026-01-02T03:04:05Z", "absolute_url": GH_URL, "content": GH_CONTENT,
          "pay_input_ranges": [{"min_cents": 10000000, "max_cents": 12000000,
                                "currency_type": "GBP", "title": "Salary", "blurb": ""}],
          "questions": [{"label": "First Name", "required": True, "fields": []},
                        {"label": "LinkedIn", "required": False, "fields": []}]}

print("ats_job · greenhouse")
route(**{GH_API: J(GH_JOB)})
r = parse(S.ats_job(GH_URL))
check("G1 live posting → live=true, title/location/updated", r and r["live"] is True
      and r["title"] == "Data Scientist" and r["location"] == "London, UK"
      and r["updated_at"] == "2026-01-02T03:04:05Z", r)
check("G1 questions=true requested", CALLS and "questions=true" in CALLS[0], CALLS)
check("G1 sponsorship lines verbatim, irrelevant sentence excluded",
      r and r["sponsorship_lines"] == ["Visa sponsorship: We do sponsor visas!",
                                       "Relocation support is available for this role."],
      r and r["sponsorship_lines"])
check("G1 requirements excerpt starts at the good-fit heading",
      r and r["requirements_excerpt"].startswith("You may be a good fit")
      and "- 5+ years of Python\n- SQL fluency" in r["requirements_excerpt"],
      r and r["requirements_excerpt"])
check("G1 questions: labels + required flags",
      r and r["questions"] == [{"label": "First Name", "required": True},
                               {"label": "LinkedIn", "required": False}], r and r["questions"])
check("G1 compensation from pay ranges",
      r and r["compensation"][0]["min"] == 100000 and r["compensation"][0]["currency"] == "GBP",
      r and r["compensation"])
big = dict(GH_JOB, content="&lt;h3&gt;Requirements&lt;/h3&gt;&lt;p&gt;" + "x " * 3000 + "&lt;/p&gt;")
route(**{GH_API: J(big)})
r = parse(S.ats_job(GH_URL))
check("G1b requirements excerpt trimmed ~1500 chars", r and len(r["requirements_excerpt"]) <= 1510,
      r and len(r["requirements_excerpt"]))

route(**{GH_API: (404, '{"status":404,"error":"Job not found"}')})
r = parse(S.ats_job(GH_URL))
check("G2 404 → live=false (not an error)", r and r["live"] is False, r)
route(**{GH_API: (500, "oops")})
out = S.ats_job(GH_URL)
check("G3 HTTP 500 → error, never live=false", is_err(out) and "500" in out, out)
route(**{GH_API: (429, "slow down")})
check("G3b HTTP 429 → error", is_err(S.ats_job(GH_URL)))
route(**{GH_API: S.FetchError("ConnectTimeout: timed out")})
out = S.ats_job(GH_URL)
check("G4 transport failure → error", is_err(out) and "unreachable" in out, out)
route(**{GH_API: (200, "<html>not json</html>")})
check("G5 200 with non-JSON body → error", is_err(S.ats_job(GH_URL)))
route(**{GH_API: (200, "[]")})
check("G5b 200 with wrong JSON shape → error", is_err(S.ats_job(GH_URL)))

route(**{"https://boards-api.greenhouse.io/v1/boards/example/jobs/777": (404, "")})
out = S.ats_job("https://careers.example.com/open-roles?gh_jid=777")
check("G6 gh_jid careers page, GUESSED board 404 → error (wrong guess ≠ closed)",
      is_err(out) and "GUESSED" in out, out)
route(**{"https://boards-api.greenhouse.io/v1/boards/example-co/jobs/777": J(GH_JOB)})
r = parse(S.ats_job("https://boards.greenhouse.io/embed/job_app?for=example-co&token=777"))
check("G7 embed URL (for=/token=) → greenhouse board+id", r and r["live"] is True, r)

print("ats_job · lever")
LV_API = "https://api.lever.co/v0/postings/example-co/abc-123"
LV_URL = "https://jobs.lever.co/example-co/abc-123"
LV_JOB = {"id": "abc-123", "text": "Credit Risk Analyst", "hostedUrl": LV_URL,
          "categories": {"location": "London", "allLocations": ["London"]},
          "createdAt": 1767225600000, "workplaceType": "hybrid",
          "description": "<div>Intro.</div>",
          "lists": [{"text": "Requirements", "content": "<li>Python</li><li>Statistics</li>"}],
          "additional": "<div>We are unable to offer visa sponsorship for this role.</div>",
          "salaryRange": {"min": 50000, "max": 60000, "currency": "GBP", "interval": "per-year"}}
route(**{LV_API: J(LV_JOB)})
r = parse(S.ats_job(LV_URL))
check("L1 live → live=true, title/location", r and r["live"] is True
      and r["title"] == "Credit Risk Analyst" and r["location"] == "London", r)
check("L1 negative sponsorship sentence quoted verbatim",
      r and r["sponsorship_lines"] == ["We are unable to offer visa sponsorship for this role."],
      r and r["sponsorship_lines"])
check("L1 requirements excerpt from lists", r and r["requirements_excerpt"]
      and r["requirements_excerpt"].startswith("Requirements"), r and r["requirements_excerpt"])
check("L1 compensation from salaryRange", r and r["compensation"]["range"]["min"] == 50000, r)
check("L1 updated_at from createdAt, labelled", r and r["updated_at"] == "2026-01-01T00:00:00Z"
      and "createdAt" in r["updated_at_basis"], r)
route(**{LV_API: (404, '{"ok":false,"error":"Document not found"}')})
r = parse(S.ats_job(LV_URL))
check("L2 404 → live=false", r and r["live"] is False, r)
route(**{LV_API: (503, "")})
check("L3 503 → error, never live=false", is_err(S.ats_job(LV_URL)))
route(**{"https://api.eu.lever.co/v0/postings/example-co/abc-123": J(LV_JOB)})
r = parse(S.ats_job("https://jobs.eu.lever.co/example-co/abc-123"))
check("L4 EU Lever host → EU API", r and r["live"] is True, r)

print("ats_job · ashby")
AB_API = "https://api.ashbyhq.com/posting-api/job-board/example-co"
AB_POST = {"id": "u-1", "title": "ML Engineer", "location": "Remote", "isRemote": True,
           "secondaryLocations": [{"location": "Berlin"}], "publishedAt": "2026-02-01",
           "jobUrl": "https://jobs.ashbyhq.com/example-co/u-1",
           "descriptionPlain": "What you'll bring\nPyTorch.\nWe offer relocation assistance.",
           "compensation": {"compensationTierSummary": "€100K – €120K"}}
route(**{AB_API: J({"jobs": [AB_POST]})})
r = parse(S.ats_job("https://jobs.ashbyhq.com/example-co/u-1"))
check("A1 id on board → live=true, comp, both locations", r and r["live"] is True
      and r["title"] == "ML Engineer" and r["location"] == "Remote | Berlin"
      and r["compensation"]["compensationTierSummary"] == "€100K – €120K", r)
check("A1 includeCompensation=true requested", CALLS and "includeCompensation=true" in CALLS[0])
check("A1 relocation sentence", r and r["sponsorship_lines"] == ["We offer relocation assistance."], r)
r = parse(S.ats_job("https://jobs.ashbyhq.com/example-co/u-2/application"))
check("A2 board loaded, id absent → live=null (unlisted-but-live possible), not false",
      r and r["live"] is None and "LISTED" in r["note"], r)
r = parse(S.ats_job("https://jobs.ashbyhq.com/example-co/U-1"))
check("A6 URL id in another case than the board's → live=true (a3 R1)", r and r["live"] is True, r)
route(**{AB_API: (404, "")})
out = S.ats_job("https://jobs.ashbyhq.com/example-co/u-1")
check("A3 board 404 → error (missing board ≠ closed posting)", is_err(out), out)
route(**{AB_API: (502, "")})
check("A4 502 → error", is_err(S.ats_job("https://jobs.ashbyhq.com/example-co/u-1")))
route(**{AB_API: J({"unexpected": True})})
check("A5 wrong shape → error", is_err(S.ats_job("https://jobs.ashbyhq.com/example-co/u-1")))

print("ats_job · unknown host")
route()  # no routes: any fetch would raise in the fake
r = parse(S.ats_job("https://careers.example.org/job/9"))
check("U1 unknown host → ats=unknown, live=null, and NOTHING fetched", r and r["ats"] == "unknown"
      and r["live"] is None and "nothing was fetched" in r["note"] and CALLS == [], (r, CALLS))
r = parse(S.ats_job("http://127.0.0.1:8460/seed/ping?focus=1"))
check("U2 loopback URL → unknown, nothing fetched (a3 R2)", r and r["live"] is None and CALLS == [],
      (r, CALLS))
check("U6 empty url → error", is_err(S.ats_job("")))

print("ats_board")
GHB = "https://boards-api.greenhouse.io/v1/boards/example-co/jobs"
jobs = [{"id": i, "title": f"Data Scientist {i}" if i % 2 else f"Recruiter {i}",
         "location": {"name": "London" if i % 3 else "New York"},
         "updated_at": "2026-03-01", "absolute_url": f"https://x/{i}"} for i in range(300)]
route(**{GHB: J({"jobs": jobs})})
r = parse(S.ats_board("example-co", "greenhouse", title_regex="data sci"))
check("B1 title filter (case-insensitive) + cap at 100", r and r["total_matched"] == 150
      and len(r["postings"]) == 100 and r["truncated"] is True, r and {k: r[k] for k in r if k != "postings"})
r = parse(S.ats_board("https://job-boards.greenhouse.io/example-co", "greenhouse",
                      title_regex="data", location_regex="^new york$"))
check("B2 URL → slug; title+location filters combine", r and r["board"] == "example-co"
      and r["total_matched"] == 50
      and all(p["location"] == "New York" for p in r["postings"]), r and r["total_matched"])
check("B2 row shape", r and set(r["postings"][0]) == {"id", "title", "location", "updated", "url"})
r = parse(S.ats_board("example-co", "greenhouse", title_regex="zzz-nothing"))
check("B3 no matches → empty list, not error", r and r["total_matched"] == 0 and r["postings"] == [])
route(**{GHB: (404, "")})
check("B4 board 404 → error, never an empty list", is_err(S.ats_board("example-co", "greenhouse")))
route(**{GHB: (500, "")})
check("B5 500 → error", is_err(S.ats_board("example-co", "greenhouse")))
check("B6 bad regex → error", is_err(S.ats_board("example-co", "greenhouse", title_regex="(")))
check("B7 unknown ats → error", is_err(S.ats_board("example-co", "workday")))
route(**{"https://api.lever.co/v0/postings/example-co?mode=json": J([LV_JOB])})
r = parse(S.ats_board("https://jobs.lever.co/example-co", "lever", location_regex="london"))
check("B8 lever board", r and r["total_matched"] == 1 and r["postings"][0]["id"] == "abc-123", r)
route(**{"https://api.lever.co/v0/postings/example-co?mode=json": J({"ok": False})})
check("B8b lever wrong shape → error", is_err(S.ats_board("example-co", "lever")))
route(**{AB_API: J({"jobs": [AB_POST]})})
r = parse(S.ats_board("example-co", "ashby", location_regex="berlin"))
check("B9 ashby board, secondary location matches", r and r["total_matched"] == 1, r)

print("uk_sponsor_check")
PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
CSV_URL = ("https://assets.publishing.service.gov.uk/media/abc123/"
           "2026-01-15_-_Worker_and_Temporary_Worker.csv")
CSV = ("﻿Organisation Name,Town/City,County,Type & Rating,Route\n"
       "Acme Analytics Ltd,London,,Worker (A rating),Skilled Worker\n"
       "Acme Analytics Ltd,London,,Worker (A rating),Global Business Mobility: Senior or Specialist Worker\n"
       "Acme Analytics Holdings Limited,Leeds,West Yorkshire,Worker (A rating),Skilled Worker\n"
       "The Acme Analytics Trust,Bristol,,Worker (B rating),Skilled Worker\n"
       "Zenith Bakery,York,,Worker (A rating),Skilled Worker\n")
PAGE_HTML = f'<a href="{CSV_URL}">Worker and Temporary Worker</a>'


def reset_cache():
    for f in Path(tmp).iterdir():
        f.unlink()
    S._parsed.update(key=None, rows=None)


reset_cache()
route(**{PAGE: (200, PAGE_HTML), CSV_URL: (200, CSV)})
r = parse(S.uk_sponsor_check(["Acme Analytics Limited", "acme analytics", "Nonexistent Org"]))
check("S1 caveat stated plainly", r and r["caveat"] == "licence-holding only; not per-role sponsorship")
check("S1 register date from filename", r and r["register_date"] == "2026-01-15", r and r["register_date"])
a, b, c = (r["results"] if r else [None] * 3)
check("S2 'X Limited' finds 'X Ltd' rows (core match), every route row returned",
      a and {(m["org"], m["route"]) for m in a["matches"]} >= {
          ("Acme Analytics Ltd", "Skilled Worker"),
          ("Acme Analytics Ltd", "Global Business Mobility: Senior or Specialist Worker")}, a)
check("S3 case-insensitive prefix + contains, typed", b and b["match_count"] == 4
      and {m["match"] for m in b["matches"]} == {"prefix", "contains"}
      and b["matches"][0]["match"] == "prefix"
      and all({"org", "town", "rating", "route"} <= set(m) for m in b["matches"]), b)
check("S4 no match → match_count 0, not an error", c and c["match_count"] == 0 and c["matches"] == [])

CALLS.clear()
ROUTES.clear()  # any network call now raises in the fake
r = parse(S.uk_sponsor_check(["Zenith Bakery"]))
check("S5 fresh cache (<24h) → no network, exact match", r and not CALLS
      and r["results"][0]["matches"][0]["match"] == "exact", (CALLS, r))

meta_p = Path(tmp) / "sponsors.meta.json"
m = json.loads(meta_p.read_text())
m["fetched_at"] = time.time() - 25 * 3600
meta_p.write_text(json.dumps(m))
route(**{PAGE: (200, PAGE_HTML.replace("2026-01-15", "2026-01-16")),
         CSV_URL.replace("2026-01-15", "2026-01-16"): (200, CSV)})
r = parse(S.uk_sponsor_check(["Zenith"]))
check("S6 cache >24h → refreshed (new register date)", r and r["register_date"] == "2026-01-16"
      and len(CALLS) == 2 and "stale" not in r, (CALLS, r and r.get("register_date")))

m = json.loads(meta_p.read_text())
m["fetched_at"] = time.time() - 48 * 3600
meta_p.write_text(json.dumps(m))
route(**{PAGE: (503, "")})
r = parse(S.uk_sponsor_check(["Zenith"]))
check("S7 refresh fails, cache 2d old → answer flagged stale with the error",
      r and r.get("stale") is True and "503" in r["refresh_error"]
      and r["results"][0]["match_count"] == 1, r)
m["fetched_at"] = time.time() - 9 * 24 * 3600
meta_p.write_text(json.dumps(m))
out = S.uk_sponsor_check(["Zenith"])
check("S8 refresh fails, cache 9d old → error, never 'no match'", is_err(out), out)

reset_cache()
route(**{PAGE: S.FetchError("ConnectTimeout")})
out = S.uk_sponsor_check(["Acme"])
check("S9 no cache + gov.uk unreachable → error", is_err(out), out)
route(**{PAGE: (200, "<p>page redesigned, no link</p>")})
out = S.uk_sponsor_check(["Acme"])
check("S10 no CSV link on page → error", is_err(out) and "CSV link" in out, out)
route(**{PAGE: (200, PAGE_HTML), CSV_URL: (200, "Name,Place\nAcme,London\n")})
out = S.uk_sponsor_check(["Acme"])
check("S11 CSV header changed → error (not zero matches)", is_err(out) and "header" in out, out)
route(**{PAGE: (200, PAGE_HTML), CSV_URL: (500, "")})
check("S12 CSV download 500 → error", is_err(S.uk_sponsor_check(["Acme"])))
check("S13 empty names → error", is_err(S.uk_sponsor_check([])))

print("plumbing")
import httpx  # noqa: E402

real_client = httpx.Client


def boom(request):
    raise httpx.ConnectError("connection refused")


reload_spec = importlib.util.spec_from_file_location("jobs_server2", REPO / "mcp" / "jobs" / "server.py")
S2 = importlib.util.module_from_spec(reload_spec)
reload_spec.loader.exec_module(S2)
S2.httpx.Client = lambda **kw: real_client(transport=httpx.MockTransport(boom), **kw)
try:
    try:
        S2._fetch("https://example.invalid/x?secret=1")
        check("P1 real _fetch wraps transport errors as FetchError", False, "no raise")
    except S2.FetchError:
        check("P1 real _fetch wraps transport errors as FetchError", True)
    out = S2.ats_job("https://jobs.lever.co/example-co/abc-123")
    check("P2 end-to-end transport failure through the real _fetch → error", is_err(out), out)
finally:
    httpx.Client = real_client
# a3 R2 arms against the REAL _fetch: a real loopback listener must see zero requests, and a
# redirect from an allowed host to loopback is refused before the hop is sent.
import http.server  # noqa: E402
import threading  # noqa: E402
HITS = []


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
reload_spec = importlib.util.spec_from_file_location("jobs_server3", REPO / "mcp" / "jobs" / "server.py")
S3 = importlib.util.module_from_spec(reload_spec)
reload_spec.loader.exec_module(S3)
for u in (f"http://127.0.0.1:{port}/seed/ping?focus=1", f"https://127.0.0.1:{port}/x"):
    try:
        S3._fetch(u)
        check(f"P5 real _fetch refuses {u.split(':')[0]} loopback", False, "no raise")
    except S3.FetchError as e:
        check(f"P5 real _fetch refuses {u.split(':')[0]} loopback", "refused" in str(e), str(e))
out = S3.ats_job(f"http://127.0.0.1:{port}/seed/ping?focus=1")
check("P6 ats_job on a loopback URL: no verdict", '"live": null' in out, out)
SEEN = []


def redirector(request):
    SEEN.append(str(request.url))
    return httpx.Response(302, headers={"location": f"http://127.0.0.1:{port}/seed/ping?focus=1"})


S3.httpx.Client = lambda **kw: real_client(transport=httpx.MockTransport(redirector), **kw)
try:
    out = S3.ats_job("https://jobs.lever.co/example-co/abc-123")
    check("P7 allowed host 302 → loopback: error, the hop never sent", is_err(out)
          and len(SEEN) == 1 and "127.0.0.1" not in SEEN[0], (out, SEEN))
finally:
    httpx.Client = real_client
time.sleep(0.2)
check("P8 the loopback listener received ZERO requests", HITS == [], HITS)
srv.shutdown()
def _try(f):
    try:
        return f()
    except Exception as e:  # noqa: BLE001 (the old _slug raised ApiError on a dotted slug: a FAIL, not a crash)
        return f"{type(e).__name__}: {e}"


check("D1 a bare DOTTED board slug is the slug, never parsed as a URL (canopus #61574)",
      _try(lambda: S._slug("acme.com", "ashby")) == "acme.com", _try(lambda: S._slug("acme.com", "ashby")))
check("D2 a board URL still yields its slug", S._slug("https://jobs.ashbyhq.com/acme.com", "ashby") == "acme.com"
      and S._slug("jobs.ashbyhq.com/acme", "ashby") == "acme")
check("D3 a plain bare slug is unchanged", S._slug("acme", "greenhouse") == "acme")
check("D4 a bare host with a query is a URL, not a slug (forge #61577 R-1)",
      _try(lambda: S._slug("boards.greenhouse.io?for=acme", "greenhouse")) == "acme",
      _try(lambda: S._slug("boards.greenhouse.io?for=acme", "greenhouse")))
check("D5 a bare ATS host names no board: the clear error, never the host as a slug (forge A-1)",
      "could not read a board slug" in str(_try(lambda: S._slug("jobs.ashbyhq.com", "ashby"))),
      _try(lambda: S._slug("jobs.ashbyhq.com", "ashby")))
s = S._scrub("ConnectError: GET https://h.example/p?token=abc&x=1 failed")
check("P3 scrub strips query strings", "token=abc" not in s and "https://h.example/p" in s, s)
check("P4 scrub caps length", len(S._scrub("x" * 5000)) <= 240)

print(f"\n{'FAIL' if fails else 'OK'}: {len(fails)} failing")
sys.exit(1 if fails else 0)
