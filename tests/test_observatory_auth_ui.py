#!/usr/bin/env python3
"""Oracle: the observatory's sign-in screens (goal 11859 U3, seed #61921; the bar is seed's #61877, the security arms are
plan-11859's F8 and I9). The screens are built against forge's U1U2 contract (POST /auth/login, POST /auth/logout, GET
/auth/me) behind a build flag, so they are inert until that lands.

  A1 inert by default: LOGIN is VITE_AUTH_UI === '1' and nothing else; AuthScreens is reached only through App.tsx's
     LOGIN-gated lazy imports (no static import anywhere), and no other module names /auth, so a default build carries
     no sign-in request at all. The owner-key door stays as it is (a3 BC-2: its retirement is U1U2's)
  A2 F8, run: auth.ts's real signIn() under node with a stubbed fetch. Two 401s whose bodies differ ("no such user",
     "wrong password", and an empty body) give ONE outcome, and its words are one constant that names how to fix it;
     signIn never reads a response body (no .json()/.text() on its path); 429 has its own words; 5xx and a network
     failure read "unreachable"; 200 is ok. The screen shows only WORDS[...]: AuthScreens never reads an `.error`
  A3 /auth/me, run: 401 is signed out, 200 with a user is signed in (malformed orgs dropped), 404 and a network
     failure are `unavailable` (the app then runs as it does without sign-in, never behind a dead form)
  A4 membership, not the building: the org list is switchable(me.orgs, …), run here: in a cog only the account's orgs
     the cog serves, on one org the account's own; the cog's room list is never the list. Picking walks (chooseOrg)
  A5 the way back is this app's: nextHash(), run under a fake location, returns '#/<route>' for a hash route and '#/'
     for an absolute URL, a protocol-relative one, a javascript: one, a sign-in loop or a malformed escape
  A6 the bar (#61877): visible labels tied to their inputs, autocomplete username/current-password, the error is a
     role=alert; "Sign in" → "Signing in…" → "Signed in"; sentence case (no uppercase utility); every control class
     has a :focus-visible ring and no outline-none; tokens only (no hex in AuthScreens or the auth CSS); nothing moves
     on its own (no animate-, ax-orb, transition or motion import in the screens: the walk is the one motion)
Seam: OBS_SRC_DIR (a mutant observatory/web/src). Exit 0 · 1 · 77 (no node).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("OBS_SRC_DIR") or REPO / "observatory" / "web" / "src")
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails.append(name)
        if detail:
            print(f"        {detail}")


def fn_body(text: str, sig: str) -> str:
    """The braces-balanced body that follows `sig` (first occurrence), or ''."""
    i = text.find(sig)
    if i < 0:
        return ""
    j = i + len(sig) - 1 if sig.endswith("{") else text.find("{\n", i)     # the body's brace, not a destructured param
    depth = 0
    for k in range(j, len(text)):
        depth += {"{": 1, "}": -1}.get(text[k], 0)
        if depth == 0:
            return text[j:k + 1]
    return ""


DRIVER = r"""
import * as A from './auth.ts'
const out = {}
const stub = (status, body) => async () => ({ ok: status >= 200 && status < 300, status,
  json: async () => { out.readBody = true; return body }, text: async () => { out.readBody = true; return JSON.stringify(body) } })
const boom = async () => { throw new TypeError('network') }
const run = async (f, fn) => { globalThis.fetch = f; return fn() }
out.login = {
  absent: await run(stub(401, { error: 'no such user' }), () => A.signIn('nobody@x.test', 'pw')),
  wrong: await run(stub(401, { error: 'wrong password' }), () => A.signIn('owner@x.test', 'pw')),
  bare: await run(stub(401, null), () => A.signIn('owner@x.test', 'pw')),
  limited: await run(stub(429, { error: 'slow' }), () => A.signIn('a@x.test', 'pw')),
  down: await run(stub(502, {}), () => A.signIn('a@x.test', 'pw')),
  net: await run(boom, () => A.signIn('a@x.test', 'pw')),
  ok: await run(stub(200, {}), () => A.signIn('a@x.test', 'pw')),
}
out.loginReadBody = !!out.readBody
out.words = A.WORDS
out.me = {
  out: await run(stub(401, {}), A.readMe),
  in: await run(stub(200, { user: 'u@x.test', orgs: [{ org: 'astryx', name: 'umairfiaz.com', role: 'owner' }, { org: 7 }, null] }), A.readMe),
  missing: await run(stub(404, {}), A.readMe),
  net: await run(boom, A.readMe),
  junk: await run(stub(200, { nope: 1 }), A.readMe),
}
const nh = (h) => { globalThis.location = { hash: h }; return A.nextHash() }
out.next = {
  route: nh('#/sign-in?next=' + encodeURIComponent('/wire/plan-1')),
  bare: nh('#/sign-in'),
  abs: nh('#/sign-in?next=' + encodeURIComponent('https://evil.test/')),
  proto: nh('#/sign-in?next=' + encodeURIComponent('//evil.test/')),
  js: nh('#/sign-in?next=' + encodeURIComponent('javascript:alert(1)')),
  loop: nh('#/sign-in?next=' + encodeURIComponent('/sign-in')),
  malformed: nh('#/sign-in?next=%E0%A4%A'),
}
console.log(JSON.stringify(out))
"""

SWITCH_DRIVER = r"""
import { switchable } from './switchable.ts'
const mine = [{ org: 'astryx', name: 'umairfiaz.com', role: 'owner' }, { org: 'elsewhere', name: 'other.example', role: 'member' }]
console.log(JSON.stringify({ cog: switchable(mine, ['astryx', 'lab']).map(o => o.org),
                             one: switchable(mine, null).map(o => o.org), none: switchable(mine, ['lab']).map(o => o.org) }))
"""


def run_node(tmp: Path, driver: str):
    (tmp / "driver.mjs").write_text(driver)
    r = subprocess.run(["node", "driver.mjs"], cwd=tmp, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None, r.stderr.strip()[-400:]
    return json.loads(r.stdout.strip().splitlines()[-1]), ""


def main():
    if not shutil.which("node"):
        print("SKIP: no node on PATH")
        return 77
    auth = (SRC / "auth.ts").read_text()
    screens = (SRC / "components" / "AuthScreens.tsx").read_text()
    app = (SRC / "App.tsx").read_text()
    css = (SRC / "index.css").read_text()

    print("A1 inert by default")
    flag = re.findall(r"export const LOGIN = (.*)", auth)
    check("LOGIN is VITE_AUTH_UI === '1' and nothing else",
          len(flag) == 1 and flag[0].strip().endswith(".env.VITE_AUTH_UI === '1'") and flag[0].count("||") == 0, flag)
    importers = [p.relative_to(SRC).as_posix() for p in SRC.rglob("*.ts*") if p.name != "AuthScreens.tsx"
                 and "components/AuthScreens" in p.read_text()]
    check("only App.tsx reaches AuthScreens", importers == ["App.tsx"], importers)
    check("App.tsx has no static import of AuthScreens", not re.search(r"^import .*AuthScreens", app, re.M))
    gate = re.search(r"const Auth = LOGIN \? \{.*?\n\} : null\n", app, re.S)
    n = gate.group(0).count("lazy(() => import('./components/AuthScreens')") if gate else 0
    check("every AuthScreens import is a lazy import inside `const Auth = LOGIN ? {…} : null`",
          n == 5 and app.count("import('./components/AuthScreens')") == 5, n)
    named = [p.relative_to(SRC).as_posix() for p in SRC.rglob("*.ts*")
             if p.name not in ("auth.ts", "AuthScreens.tsx") and re.search(r"['\"`]/auth/", p.read_text())]
    check("no other module names /auth", named == [], named)
    check("the owner-key door is still there (a3 BC-2: retired in U1U2, not here)",
          "function KeyBadge()" in app and "<KeyBadge />" in app and "saveObsKey(val.trim())" in app)

    tmp = Path(tempfile.mkdtemp(prefix="authui-"))
    try:
        # the real module, its build-time flag line pinned (node has no import.meta.env); nothing else changed
        src = re.sub(r"^export const LOGIN = .*$", "export const LOGIN = false", auth, count=1, flags=re.M)
        (tmp / "auth.ts").write_text(src)
        res, err = run_node(tmp, DRIVER)
        check("auth.ts runs under node", res is not None, err)
        if res is None:
            return 1
        L, W = res["login"], res["words"]
        print("A2 F8: a failed sign-in never says which part failed")
        check("absent user, wrong password and a bare 401 are ONE outcome",
              L["absent"] == L["wrong"] == L["bare"] == "mismatch", L)
        check("signIn never reads a response body", res["loginReadBody"] is False)
        check("the 401 words name the fix and no part", "Check both" in W["mismatch"]
              and not re.search(r"no account|not found|unknown|wrong password|incorrect password", W["mismatch"], re.I), W["mismatch"])
        check("429 has its own words", L["limited"] == "slow-down" and W["slow-down"] != W["mismatch"] and "Wait" in W["slow-down"])
        check("5xx and a network failure read unreachable; 200 is ok",
              L["down"] == L["net"] == "unreachable" and L["ok"] == "ok", L)
        check("the screens show WORDS only, never a server's `.error`",
              ".error" not in screens.replace("setError", "").replace("auth-error", "") and "WORDS[out]" in screens)

        print("A3 /auth/me")
        M = res["me"]
        check("401 is signed out", M["out"] == {"state": "out"}, M["out"])
        check("200 is signed in, malformed orgs dropped",
              M["in"] == {"state": "in", "me": {"user": "u@x.test", "orgs": [{"org": "astryx", "name": "umairfiaz.com", "role": "owner"}]}}, M["in"])
        check("404, a network failure and a bodiless 200 are unavailable",
              all(M[k] == {"state": "unavailable"} for k in ("missing", "net", "junk")), M)

        print("A4 membership, not the building")
        sw = fn_body(screens, "export function switchable(")
        (tmp / "switchable.ts").write_text("type AuthOrg = { org: string; name: string; role: string }\n"
                                          "export function switchable(mine: AuthOrg[], cogOrgs: string[] | null): AuthOrg[] " + sw)
        s2, err = run_node(tmp, SWITCH_DRIVER)
        check("switchable: a cog lists only your orgs it serves; one org lists yours",
              s2 == {"cog": ["astryx"], "one": ["astryx", "elsewhere"], "none": []}, s2 or err)
        ol = fn_body(screens, "function OrgList(")
        check("the org list is switchable(me.orgs, …), and picking an org walks (chooseOrg)",
              re.findall(r"const orgs = (.*)", ol) == ["switchable(me.orgs, cog.cog ? cog.orgs.map((o) => o.org ?? '').filter(Boolean) : null)"]
              and "chooseOrg(o.org)" in ol and "orgs.map((o) => {" in ol, re.findall(r"const orgs = (.*)", ol))

        print("A5 the way back is this app's")
        N = res["next"]
        check("a hash route comes back as itself", N["route"] == "#/wire/plan-1", N["route"])
        check("absolute, protocol-relative, javascript:, a sign-in loop, malformed: all '#/'",
              all(N[k] == "#/" for k in ("bare", "abs", "proto", "js", "loop", "malformed")), N)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("A6 the bar")
    for i, auto in (("auth-email", "username"), ("auth-password", "current-password")):
        check(f"{i}: a visible label tied to it, autocomplete {auto}",
              f'id="{i}"' in screens and f'auto="{auto}"' in screens and 'htmlFor={id}' in screens and 'id={id}' in screens)
    check("the error is a role=alert the inputs point at", 'id="auth-error" role="alert"' in screens and "aria-describedby" in screens)
    check("Sign in → Signing in… → Signed in", all(w in screens for w in ("'Signing in…'", "'Signed in'", "'Sign in'")))
    check("sentence case: no uppercase utility", not re.search(r"\buppercase\b|text-transform", screens))
    block = css[css.find("/* SIGN-IN"):]
    classes = ["auth-field", "auth-primary", "auth-link", "auth-org", "auth-chip"]
    check("every control class has a :focus-visible ring", all(f".{c}:focus-visible" in block for c in classes)
          and "outline: 2px solid var(--t-accent2)" in block)
    check("no outline-none in the screens", "outline-none" not in screens)
    check("tokens only: no hex in AuthScreens or the auth CSS",
          not re.search(r"#[0-9a-fA-F]{3,8}\b", screens) and not re.search(r"#[0-9a-fA-F]{3,8}\b", block))
    check("nothing moves on its own: no animate-, ax-orb, transition or motion import",
          not re.search(r"animate-|ax-orb|transition|from 'motion", screens) and "animation" not in block and "transition" not in block)

    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
