#!/usr/bin/env python3
"""astryx · jobs MCP server — public job-posting facts from the ATS's own JSON API, no browser.

Three tools:
  ats_job(url)            one posting: live?, title, location, comp, sponsorship sentences,
                          requirements excerpt, application questions
  ats_board(board, ats)   live postings on a Greenhouse / Lever / Ashby board, regex-filtered
  uk_sponsor_check(names) UK Home Office Register of Licensed Sponsors (Workers) lookup

Generic: no candidate, company or target data lives here. Every request goes to a PUBLIC,
unauthenticated endpoint; no .env secret is needed (JOBS_HTTP_TIMEOUT / JOBS_CACHE_DIR are
optional overrides).

FAIL CLOSED. A transport error, a 5xx, a 429 or an unparseable body comes back as
"error: ...", never as live=false or "no match". live=false is said only when the ATS itself
answered "this posting is not there" (404/410, or a board that loaded without that id).

Granted per charter (`Grants: jobs`)."""
from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import time
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import logging

import httpx
from mcp.server.fastmcp import FastMCP

logging.getLogger("httpx").setLevel(logging.WARNING)  # no per-request URL lines on stderr

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))   # astryx.paths: the org's estate (its HOME in a cog of several orgs), plan-11324 S3a
from astryx import config, paths  # noqa: E402


def _env() -> dict[str, str]:
    try:
        return {k.strip(): v.strip() for k, v in
                (l.split("=", 1) for l in (paths.estate(__file__) / ".env").read_text().splitlines()
                 if "=" in l and not l.lstrip().startswith("#"))}
    except OSError:
        return {}


_cfg = _env()
TIMEOUT = float(_cfg.get("JOBS_HTTP_TIMEOUT") or 20)
CACHE_DIR = Path(config.org_env("JOBS_CACHE_DIR") or _cfg.get("JOBS_CACHE_DIR")
                 or paths.estate(__file__) / "var" / "cache" / "jobs")
UA = "astryx-jobs/1.0 (+public job-posting lookup)"

SPONSOR_PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
SPONSOR_TTL = 24 * 3600          # refresh the register when older than this
SPONSOR_STALE_MAX = 7 * 24 * 3600  # a failed refresh may fall back to a cache this young, flagged
CAVEAT = "licence-holding only; not per-role sponsorship"
BOARD_CAP = 100
EXCERPT_CHARS = 1500

mcp = FastMCP("astryx-jobs")


# ── http + errors ────────────────────────────────────────────────────────────

class FetchError(Exception):
    """Transport-level failure (no HTTP answer at all)."""


def _scrub(e: BaseException | str) -> str:
    """Error text safe for the step stream: no query strings, no long dumps."""
    s = e if isinstance(e, str) else f"{type(e).__name__}: {e}"
    s = re.sub(r"(https?://[^\s?#'\"]+)[?#][^\s'\"]*", r"\1?…", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:240]


# The only hosts this server ever talks to: the ATS public APIs and gov.uk. Every request,
# redirect hops included, is checked against it, so a URL read from a job email or page can
# never steer a fetch at this machine's own services (a3 R2: SSRF to loopback).
ALLOWED_HOSTS = frozenset({
    "boards-api.greenhouse.io", "api.lever.co", "api.eu.lever.co", "api.ashbyhq.com",
    "www.gov.uk", "assets.publishing.service.gov.uk"})


def _host_gate(request: httpx.Request) -> None:
    if request.url.scheme != "https" or (request.url.host or "").lower() not in ALLOWED_HOSTS:
        raise FetchError(f"refused: {request.url.scheme}://{request.url.host} is not an allowed host")


def _fetch(url: str) -> tuple[int, str]:
    """GET → (status, body text). Raises FetchError when no HTTP answer arrives or the host
    (on any redirect hop) is not in ALLOWED_HOSTS. The one network seam: tests replace it."""
    try:
        with httpx.Client(timeout=httpx.Timeout(TIMEOUT, connect=min(TIMEOUT, 10)),
                          follow_redirects=True, headers={"User-Agent": UA},
                          event_hooks={"request": [_host_gate]}) as c:
            r = c.get(url)
            return r.status_code, r.text
    except httpx.HTTPError as e:
        raise FetchError(_scrub(e)) from None


class ApiError(Exception):
    pass


def _get_json(url: str, what: str) -> tuple[int, object | None]:
    """(status, parsed) for 200; (404|410, None) for not-found; ApiError otherwise."""
    try:
        status, body = _fetch(url)
    except FetchError as e:
        raise ApiError(f"{what} unreachable ({e})") from None
    if status in (404, 410):
        return status, None
    if status != 200:
        raise ApiError(f"{what} answered HTTP {status}")
    try:
        return status, json.loads(body)
    except ValueError:
        raise ApiError(f"{what} returned a non-JSON body") from None


def _err(msg: str) -> str:
    return "error: " + _scrub(msg)


# ── text helpers ─────────────────────────────────────────────────────────────

_BLOCK = re.compile(r"(?i)<\s*(br|/p|/div|/li|/h[1-6]|/ul|/ol|/tr|p|div|h[1-6])\b[^>]*>")


def _html_to_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(s)  # Greenhouse ships entity-escaped HTML: unescape first
    s = re.sub(r"(?i)<\s*li\b[^>]*>", "\n- ", s)
    s = _BLOCK.sub("\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in s.splitlines()]
    s = re.sub(r"(?m)^-\n+(?=[^\n-])", "- ", "\n".join(lines))  # "<li><p>x" → "- x"
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"(?m)^(- .*)\n\n(?=- )", r"\1\n", s)             # tighten bullet runs
    s = re.sub(r"(?m)^(- .*)\n\n(?=- )", r"\1\n", s)             # (overlapping pairs)
    return s.strip()


_SPONSOR_RX = re.compile(r"(?i)visa|sponsor|relocat|work permit|right to work|work authori[sz]")


def _sponsorship_lines(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z(\"'])", line):
            sent = sent.strip(" -•\t")
            if sent and _SPONSOR_RX.search(sent) and sent not in out:
                out.append(sent)
    return out


_REQ_HEAD = re.compile(
    r"(?i)^\W*(you (may|might) be a good fit|requirements|minimum qualifications|"
    r"basic qualifications|qualifications|what you('ll| will)? bring|about you|who you are|"
    r"what we('re| are)? looking for|you (will )?have|you should have|must[- ]haves?|"
    r"skills (and|&) experience|experience (and|&) skills|your profile|ideal candidate)")


def _requirements_excerpt(text: str) -> str | None:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if len(line) <= 90 and _REQ_HEAD.search(line):
            chunk = "\n".join(lines[i:]).strip()
            return chunk if len(chunk) <= EXCERPT_CHARS else chunk[:EXCERPT_CHARS].rstrip() + " …"
    return None


def _iso_ms(ms) -> str | None:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ms) / 1000))
    except (TypeError, ValueError):
        return None


# ── ATS detection ────────────────────────────────────────────────────────────

def _detect(url: str) -> dict:
    """→ {ats, ...ids} or {ats: 'unknown'}."""
    u = urlparse(url if "://" in url else "https://" + url)
    host = (u.hostname or "").lower()
    parts = [p for p in u.path.split("/") if p]
    q = parse_qs(u.query)

    if host.endswith("greenhouse.io"):
        board = (q.get("for") or [None])[0]
        jid = (q.get("token") or q.get("gh_jid") or [None])[0]
        if "jobs" in parts:
            i = parts.index("jobs")
            if i >= 1 and not board:
                board = parts[i - 1]
            if len(parts) > i + 1 and not jid:
                jid = parts[i + 1]
        if board and jid and jid.isdigit():
            return {"ats": "greenhouse", "board": board, "id": jid, "board_guessed": False}
    if "gh_jid" in q and q["gh_jid"][0].isdigit():
        # a company careers page wrapping Greenhouse: the board token isn't in the URL.
        board = (q.get("for") or q.get("board") or [None])[0]
        guessed = board is None
        if guessed:
            labels = [l for l in host.split(".") if l not in ("www", "careers", "jobs", "boards")]
            board = labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")
        return {"ats": "greenhouse", "board": board, "id": q["gh_jid"][0],
                "board_guessed": guessed}
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and len(parts) >= 2:
        api = "api.eu.lever.co" if ".eu." in host else "api.lever.co"
        return {"ats": "lever", "company": parts[0], "id": parts[1], "api": api}
    if host == "jobs.ashbyhq.com" and len(parts) >= 2:
        return {"ats": "ashby", "org": parts[0], "id": parts[1]}
    return {"ats": "unknown"}


# ── per-ATS posting fetchers (return dict, or raise ApiError) ────────────────

def _base(ats: str, url: str, live: bool | None) -> dict:
    return {"ats": ats, "live": live, "title": None, "location": None, "updated_at": None,
            "compensation": None, "sponsorship_lines": [], "requirements_excerpt": None,
            "questions": None, "url": url}


def _fill_text(out: dict, text: str) -> None:
    out["sponsorship_lines"] = _sponsorship_lines(text)
    out["requirements_excerpt"] = _requirements_excerpt(text)


def _greenhouse_job(d: dict, url: str) -> dict:
    api = (f"https://boards-api.greenhouse.io/v1/boards/{d['board']}/jobs/{d['id']}"
           "?questions=true&pay_transparency=true")
    status, j = _get_json(api, "Greenhouse API")
    if j is None:
        if d.get("board_guessed"):
            # 404 could mean "wrong board guess", not "closed": never a false live=false.
            raise ApiError(f"Greenhouse 404 for a GUESSED board token '{d['board']}'; "
                           "pass the job-boards.greenhouse.io/<board>/jobs/<id> URL")
        return {**_base("greenhouse", url, False), "http_status": status}
    if not isinstance(j, dict):
        raise ApiError("Greenhouse API returned an unexpected shape")
    out = _base("greenhouse", j.get("absolute_url") or url, True)
    out["title"] = j.get("title")
    out["location"] = (j.get("location") or {}).get("name")
    out["updated_at"] = j.get("updated_at")
    pay = j.get("pay_input_ranges") or []
    if pay:
        out["compensation"] = [{
            "title": p.get("title"),
            "min": (p.get("min_cents") or 0) / 100 if p.get("min_cents") is not None else None,
            "max": (p.get("max_cents") or 0) / 100 if p.get("max_cents") is not None else None,
            "currency": p.get("currency_type"),
            "blurb": _html_to_text(p.get("blurb")) or None} for p in pay]
    qs = j.get("questions")
    if isinstance(qs, list):
        out["questions"] = [{"label": q.get("label"), "required": bool(q.get("required"))}
                            for q in qs]
    _fill_text(out, _html_to_text(j.get("content")))
    if d.get("board_guessed"):
        out["note"] = f"board token '{d['board']}' was guessed from the host"
    return out


def _lever_job(d: dict, url: str) -> dict:
    api = f"https://{d['api']}/v0/postings/{d['company']}/{d['id']}"
    status, j = _get_json(api, "Lever API")
    if j is None:
        return {**_base("lever", url, False), "http_status": status}
    if not isinstance(j, dict) or "text" not in j:
        raise ApiError("Lever API returned an unexpected shape")
    out = _base("lever", j.get("hostedUrl") or url, True)
    out["title"] = j.get("text")
    cat = j.get("categories") or {}
    locs = cat.get("allLocations") or []
    out["location"] = " | ".join(locs) if locs else cat.get("location")
    out["updated_at"] = _iso_ms(j.get("createdAt"))
    out["updated_at_basis"] = "Lever exposes createdAt only"
    comp = {}
    if j.get("salaryRange"):
        comp["range"] = j["salaryRange"]
    if j.get("salaryDescriptionPlain") or j.get("salaryDescription"):
        comp["description"] = (j.get("salaryDescriptionPlain")
                               or _html_to_text(j.get("salaryDescription")))
    out["compensation"] = comp or None
    if j.get("workplaceType"):
        out["workplace_type"] = j["workplaceType"]
    parts = [_html_to_text(j.get("description"))]
    for li in j.get("lists") or []:
        parts.append(f"{li.get('text', '')}\n{_html_to_text(li.get('content'))}")
    parts.append(_html_to_text(j.get("additional")))
    _fill_text(out, "\n\n".join(p for p in parts if p))
    return out


def _ashby_board(org: str) -> list[dict]:
    api = f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"
    status, j = _get_json(api, "Ashby API")
    if j is None:
        raise ApiError(f"Ashby board '{org}' not found (HTTP {status})")
    if not isinstance(j, dict) or not isinstance(j.get("jobs"), list):
        raise ApiError("Ashby API returned an unexpected shape")
    return j["jobs"]


def _ashby_location(p: dict) -> str | None:
    locs = [p.get("location")] + [s.get("location") for s in p.get("secondaryLocations") or []
                                  if isinstance(s, dict)]
    locs = [l for l in locs if l]
    return " | ".join(locs) if locs else None


def _ashby_job(d: dict, url: str) -> dict:
    jobs = _ashby_board(d["org"])
    want = d["id"].strip().lower()
    p = next((x for x in jobs if str(x.get("id") or "").strip().lower() == want), None)
    if p is None:
        # The job-board API lists LISTED postings only; a live direct-link (unlisted) posting is
        # absent too. Absence is therefore not "the board says it's gone": no verdict (a3 R1).
        out = _base("ashby", url, None)
        out["note"] = ("board loaded; this id is not among its LISTED postings: closed, or "
                       "unlisted but live. No verdict; open the link to check")
        return out
    out = _base("ashby", p.get("jobUrl") or url, True)
    out["title"] = p.get("title")
    out["location"] = _ashby_location(p)
    out["updated_at"] = p.get("updatedAt") or p.get("publishedAt")
    if p.get("isRemote") is not None:
        out["is_remote"] = p.get("isRemote")
    comp = p.get("compensation")
    if comp:
        out["compensation"] = {k: comp.get(k) for k in
                               ("compensationTierSummary", "scrapeableCompensationSalarySummary")
                               if comp.get(k)} or comp
    text = p.get("descriptionPlain") or _html_to_text(p.get("descriptionHtml"))
    _fill_text(out, text)
    return out


def _unknown_job(url: str) -> dict:
    # No fetch: an arbitrary URL (often from an email or a page) is never requested (a3 R2).
    return {"ats": "unknown", "url": url, "live": None,
            "note": "not a Greenhouse/Lever/Ashby URL; nothing was fetched. "
                    "Find the posting's ATS link, or open it in a browser"}


@mcp.tool()
def ats_job(url: str) -> str:
    """One public job posting, read from its ATS's public JSON API (Greenhouse, Lever, Ashby).
    Returns JSON: ats, live, title, location, updated_at, compensation, sponsorship_lines
    (verbatim sentences mentioning visa/sponsor/relocation/right-to-work), requirements_excerpt,
    questions (label + required, Greenhouse only), url. live=false ONLY when the ATS said the
    posting is gone; any API failure is "error: ...". live=null means no verdict (an Ashby id absent from its
    listed postings). Unknown hosts → ats='unknown', live=null, and nothing is fetched."""
    url = (url or "").strip()
    if not url:
        return _err("empty url")
    d = _detect(url)
    try:
        if d["ats"] == "greenhouse":
            out = _greenhouse_job(d, url)
        elif d["ats"] == "lever":
            out = _lever_job(d, url)
        elif d["ats"] == "ashby":
            out = _ashby_job(d, url)
        else:
            out = _unknown_job(url if "://" in url else "https://" + url)
    except ApiError as e:
        return _err(str(e))
    except Exception as e:  # parsing surprises: fail closed, never a verdict
        return _err(f"{d['ats']}: {_scrub(e)}")
    return json.dumps(out, ensure_ascii=False, indent=1)


# ── boards ───────────────────────────────────────────────────────────────────

_ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com")


def _slug(board: str, ats: str) -> str:
    b = board.strip()
    host = b.split("?", 1)[0].lower()
    if "/" not in b and "?" not in b and not host.endswith(_ATS_HOSTS):   # a bare slug, dotted ones too (Ashby has
        return b                        # "acme.com"); a URL has a "/" or a "?", and a bare ATS host names no board
    u = urlparse(b if "://" in b else "https://" + b)
    q = parse_qs(u.query)
    if ats == "greenhouse" and q.get("for"):
        return q["for"][0]
    parts = [p for p in u.path.split("/") if p]
    if ats == "greenhouse" and parts and parts[0] == "embed":
        parts = parts[1:]
    if not parts:
        raise ApiError("could not read a board slug from that URL")
    return parts[0]


@mcp.tool()
def ats_board(board_url_or_slug: str, ats: str, title_regex: str = "",
              location_regex: str = "") -> str:
    """Live postings on one Greenhouse / Lever / Ashby board (ats = greenhouse|lever|ashby),
    filtered by case-insensitive title_regex / location_regex. JSON rows of id, title, location,
    updated, url; capped at 100 (total_matched says how many matched). A missing board or an API
    failure is "error: ...", never an empty list."""
    ats = (ats or "").strip().lower()
    if ats not in ("greenhouse", "lever", "ashby"):
        return _err("ats must be greenhouse, lever or ashby")
    try:
        tr = re.compile(title_regex, re.I) if title_regex else None
        lr = re.compile(location_regex, re.I) if location_regex else None
    except re.error as e:
        return _err(f"bad regex: {e}")
    try:
        slug = _slug(board_url_or_slug or "", ats)
        if not slug:
            return _err("empty board")
        rows: list[dict] = []
        if ats == "greenhouse":
            _, j = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                             "Greenhouse API")
            if j is None:
                raise ApiError(f"Greenhouse board '{slug}' not found")
            if not isinstance(j, dict) or not isinstance(j.get("jobs"), list):
                raise ApiError("Greenhouse API returned an unexpected shape")
            for p in j["jobs"]:
                rows.append({"id": str(p.get("id")), "title": p.get("title"),
                             "location": (p.get("location") or {}).get("name"),
                             "updated": p.get("updated_at"), "url": p.get("absolute_url")})
        elif ats == "lever":
            host = "api.eu.lever.co" if "eu.lever.co" in board_url_or_slug else "api.lever.co"
            _, j = _get_json(f"https://{host}/v0/postings/{slug}?mode=json", "Lever API")
            if j is None:
                raise ApiError(f"Lever board '{slug}' not found")
            if not isinstance(j, list):
                raise ApiError("Lever API returned an unexpected shape")
            for p in j:
                cat = p.get("categories") or {}
                locs = cat.get("allLocations") or []
                rows.append({"id": p.get("id"), "title": p.get("text"),
                             "location": " | ".join(locs) if locs else cat.get("location"),
                             "updated": _iso_ms(p.get("createdAt")), "url": p.get("hostedUrl")})
        else:
            for p in _ashby_board(slug):
                rows.append({"id": p.get("id"), "title": p.get("title"),
                             "location": _ashby_location(p),
                             "updated": p.get("updatedAt") or p.get("publishedAt"),
                             "url": p.get("jobUrl")})
    except ApiError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"{ats}: {_scrub(e)}")
    hit = [r for r in rows
           if (not tr or tr.search(r["title"] or ""))
           and (not lr or lr.search(r["location"] or ""))]
    return json.dumps({"ats": ats, "board": slug, "total_on_board": len(rows),
                       "total_matched": len(hit), "truncated": len(hit) > BOARD_CAP,
                       "postings": hit[:BOARD_CAP]}, ensure_ascii=False, indent=1)


# ── UK sponsor register ──────────────────────────────────────────────────────

_CSV_RX = re.compile(r"https://assets\.publishing\.service\.gov\.uk/[^\"'\s<>]+?\.csv")
_REG_COLS = ("Organisation Name", "Town/City", "Type & Rating", "Route")
_LEGAL = re.compile(r"\b(limited|ltd|plc|llp|llc|inc|incorporated|corp|corporation|"
                    r"company|co|uk|group|holdings)\b\.?")
_parsed: dict = {"key": None, "rows": None}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w&]+", " ", (s or "").casefold())).strip()


def _core(s: str) -> str:
    return re.sub(r"\s+", " ", _LEGAL.sub(" ", _norm(s))).strip()


def _register_date(url: str) -> str | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", url.rsplit("/", 1)[-1])
    return m.group(1) if m else None


def _refresh_register() -> dict:
    """Download the current register CSV into the cache. Raises ApiError."""
    try:
        status, page = _fetch(SPONSOR_PAGE)
    except FetchError as e:
        raise ApiError(f"gov.uk register page unreachable ({e})") from None
    if status != 200:
        raise ApiError(f"gov.uk register page answered HTTP {status}")
    m = _CSV_RX.search(page)
    if not m:
        raise ApiError("no register CSV link found on the gov.uk page (layout changed?)")
    csv_url = html.unescape(m.group(0))
    try:
        status, body = _fetch(csv_url)
    except FetchError as e:
        raise ApiError(f"register CSV unreachable ({e})") from None
    if status != 200:
        raise ApiError(f"register CSV answered HTTP {status}")
    _check_header(body)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_DIR / "sponsors.csv.tmp"
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(CACHE_DIR / "sponsors.csv")
    meta = {"source_url": csv_url, "register_date": _register_date(csv_url),
            "fetched_at": time.time()}
    (CACHE_DIR / "sponsors.meta.json").write_text(json.dumps(meta))
    return meta


def _check_header(body: str) -> None:
    head = next(csv.reader(io.StringIO(body.lstrip("﻿"))), [])
    missing = [c for c in _REG_COLS if c not in [h.strip() for h in head]]
    if missing:
        raise ApiError(f"register CSV header changed; missing {missing}")


def _load_register() -> tuple[dict, list[dict]]:
    meta_p, csv_p = CACHE_DIR / "sponsors.meta.json", CACHE_DIR / "sponsors.csv"
    meta = None
    try:
        meta = json.loads(meta_p.read_text()) if csv_p.exists() else None
    except (OSError, ValueError):
        meta = None
    age = time.time() - meta["fetched_at"] if meta else None
    if meta is None or age > SPONSOR_TTL:
        try:
            meta = _refresh_register()
        except ApiError as e:
            if meta is None or age > SPONSOR_STALE_MAX:
                raise
            meta = {**meta, "stale": True,
                    "refresh_error": _scrub(str(e)),
                    "warning": f"refresh failed; using a cache {age / 3600:.0f}h old"}
    key = (str(csv_p), csv_p.stat().st_mtime)
    if _parsed["key"] != key:
        body = csv_p.read_text(encoding="utf-8")
        _check_header(body)
        rows = []
        for r in csv.DictReader(io.StringIO(body.lstrip("﻿"))):
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            name = r.get("Organisation Name", "")
            rows.append({"org": name, "town": r.get("Town/City", ""),
                         "county": r.get("County", ""), "rating": r.get("Type & Rating", ""),
                         "route": r.get("Route", ""), "_n": _norm(name), "_c": _core(name)})
        _parsed.update(key=key, rows=rows)
    return meta, _parsed["rows"]


@mcp.tool()
def uk_sponsor_check(names: list[str]) -> str:
    """Look organisations up on the UK Home Office Register of Licensed Sponsors (Workers).
    Case-insensitive exact / prefix / contains match, plus a legal-suffix-stripped 'core'
    contains match (so 'X Limited' finds 'X Ltd'). Returns every matching row (org, town,
    rating, route) and the register date. Licence-holding only; not per-role sponsorship.
    A download/parse failure is "error: ...", never "no match"."""
    if isinstance(names, str):
        names = [names]
    names = [n for n in (names or []) if isinstance(n, str) and n.strip()][:50]
    if not names:
        return _err("no names given")
    try:
        meta, rows = _load_register()
    except ApiError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"register: {_scrub(e)}")
    if not rows:
        return _err("register parsed to zero rows")
    rank = {"exact": 0, "prefix": 1, "contains": 2, "core_contains": 3}
    results = []
    for q in names:
        qn, qc = _norm(q), _core(q)
        hits = []
        for r in rows:
            if r["_n"] == qn:
                t = "exact"
            elif r["_n"].startswith(qn):
                t = "prefix"
            elif qn in r["_n"]:
                t = "contains"
            elif len(qc) >= 3 and qc in r["_c"]:
                t = "core_contains"
            else:
                continue
            hits.append({"org": r["org"], "town": r["town"], "county": r["county"],
                         "rating": r["rating"], "route": r["route"], "match": t})
        hits.sort(key=lambda h: (rank[h["match"]], h["org"]))
        results.append({"query": q, "match_count": len(hits), "truncated": len(hits) > 50,
                        "matches": hits[:50]})
    out = {"caveat": CAVEAT, "register_date": meta.get("register_date"),
           "source_url": meta.get("source_url"),
           "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(meta["fetched_at"])),
           "rows_in_register": len(rows), "results": results}
    for k in ("stale", "warning", "refresh_error"):
        if k in meta:
            out[k] = meta[k]
    return json.dumps(out, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    mcp.run()
