#!/usr/bin/env python3
"""Oracle: the cog in the observatory's UI (the owner's ask 10-19: "make the cog well integrated in observatory",
following skills/astryx-design). The building (components/CogBuilding.tsx) is the cog seen as one building with
several rooms: the header's room chips, the building sheet, the chooser. Read from the source, the repo's way
(tests/test_observatory_no_budget_ui.py); the build (npm run build) is the type-check, a real browser the look.

  K1 the owner key rides only to a base safeBase admits: safeBase's own pattern (read from cog.tsx, run here) admits
     "/" and "/o/<registry name>/" and refuses every other origin or shape; roomGet refuses an unsafe base before any
     fetch; CogBuilding.tsx fetches nothing itself (every room read is cog.tsx's); AgentFace's room base is checked
  K2 one org renders as before: App mounts the switcher only under cog.cog, the building reads nothing unless
     cog.cog, and the chooser is called only while a cog has no room chosen
  K3 the design language: no hex colour in the new code (tokens only); every async room state has its words
     (reading, down, private, empty as a promise); a looping motion checks reduced motion; icon-only buttons carry an
     aria-label and a title; the sheet is portalled (the header is its own stacking context: inside it the sheet sat
     under the sidebar, seen in chromium 10-19)
  K5 the floor's camera frames the FOCUSED org (owner 10-19: "the center of floor to the focused org only, not the
     overall cog center"): fit() centres on the chosen room's own centre (one.w * me + one.w / 2) at a one-room scale,
     the floor's first framing is that, and only the ⤢ control frames every room
Seam: OBS_SRC_DIR (a mutant observatory/web/src). Exit 0 · 1 · 77.
"""
import os
import re
import sys
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


def code(text: str) -> str:
    """Strip // and /* */ comments (not inside strings or template literals). JSX text can carry an apostrophe, so this
    reads .ts-style code only; JSX files are scanned for comments by line instead (strip_jsx)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"`":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def main():
    files = {n: SRC / p for n, p in (("cog", "cog.tsx"), ("building", "components/CogBuilding.tsx"),
                                      ("app", "App.tsx"), ("face", "components/AgentFace.tsx"))}
    missing = [str(p) for p in files.values() if not p.is_file()]
    if missing:
        print(f"SKIP (77): {missing} absent")
        return 77
    raw = {n: p.read_text() for n, p in files.items()}
    src = {n: code(t) for n, t in raw.items()}

    print("K1 THE KEY RIDES ONLY TO A SAFE BASE")
    m = re.search(r"safeBase = \(b: unknown\): b is string => typeof b === 'string' && /(.+?)/\.test\(b\)", raw["cog"])
    pat = re.compile(m.group(1)) if m else None
    good = ["/", "/o/lab/", "/o/astryx/", "/o/fx-1.b_2/"]
    bad = ["", "//evil.example/", "https://evil.example/", "/o/", "/o/lab", "/o/../", "/o/Lab/", "/o/lab/x/",
           "/o/lab/?", "/api/", " /", "/o/-lab/"]
    check("safeBase admits / and /o/<registry name>/ only", bool(pat) and all(pat.fullmatch(b) for b in good)
          and not any(pat.search(b) for b in bad), "pattern not found" if not pat else
          str([b for b in bad if pat.search(b)] + [b for b in good if not pat.fullmatch(b)]))
    rg = re.search(r"export async function roomGet<T>\(base: string, path: string\)[^{]*\{(.*?)\n\}", src["cog"], re.S)
    body = rg.group(1) if rg else ""
    check("roomGet refuses an unsafe base before it fetches", rg is not None
          and 0 <= body.find("if (!safeBase(base)) throw") < body.find("fetch("), body[:200])
    check("CogBuilding.tsx fetches nothing itself (every room read is cog.tsx's)",
          not re.search(r"\bfetch\(|EventSource\(", src["building"]))
    check("AgentFace's room base is safeBase-checked, else the focused org's own base (/ on one org)",
          "base && safeBase(base) ? base : focusBase()" in src["face"] and "`${room}api/agents/" in src["face"]
          and "FOCUS = base && safeBase(base) ? base : '/'" in src["cog"])
    check("the building reads every room through readLive (readRoom + roomGet)",
          re.search(r"readRoom\(o\.base\), roomGet<Overview>\(o\.base, '/overview'\)", src["cog"]) is not None)

    print("\nK2 ONE ORG AS BEFORE")
    check("App mounts the switcher only under cog.cog", "{cog.cog ? <CogSwitcher /> : overview && (" in src["app"])
    check("the building reads nothing unless cog.cog",
          "const orgs = cog.cog ? cog.orgs.filter(" in src["cog"] and "if (!orgs.length) return" in src["cog"]
          and "if (!cog.cog) return <>{children}</>" in src["cog"])
    check("the chooser only while a cog has no room chosen",
          "const choosing = cog.cog && !cog.orgs.some(o => o.org === pick)" in src["cog"]
          and "{choosing ? chooser(cog) : children}" in src["cog"])

    print("\nK3 THE DESIGN LANGUAGE")
    hexes = {n: re.findall(r"#[0-9a-fA-F]{3,8}\b", src[n]) for n in ("building", "cog")}
    check("no hex colour in the new code: tokens only", not any(hexes.values()), str(hexes))
    b = raw["building"]
    words = {"reading": "Knocking on", "down": "isn't answering", "locked": "private to its own key",
             "empty (a promise)": "No one has moved in yet", "chip": "reading…"}
    check("every async room state has its words", all(w in b for w in words.values()),
          str([k for k, w in words.items() if w not in b]))
    check("a looping motion checks reduced motion", "repeat: Infinity" in b and "useReducedMotion()" in b
          and re.search(r"working && !still \? \{ duration: 2\.2, repeat: Infinity", b) is not None)
    icon_buttons = [x for x in re.findall(r"<button\b(?:(?!</button>).)*?<(?:BuildingIcon|CloseIcon) />", b, re.S) if x.count("<button") == 1]
    check("icon-only buttons carry an aria-label and a title", len(icon_buttons) == 2
          and all("aria-label=" in x and "title=" in x for x in icon_buttons), str(len(icon_buttons)))
    check("the building sheet is portalled to the body", "createPortal(" in src["building"]
          and "document.body," in src["building"])

    print("\nK4 A NEW ORG FROM THE AGENTS VIEW")
    no, people = SRC / "components" / "CogNewOrg.tsx", SRC / "components" / "PeopleView.tsx"
    if not no.is_file() or not people.is_file():
        check("CogNewOrg.tsx and PeopleView.tsx present", False, str(no))
        return 1
    n, pv = code(no.read_text()), code(people.read_text())
    check("the Agents view offers New org and the rooms in the making to the owner only",
          "actions={who.owner && <>" in pv and "<NewOrgButton " in pv and "{who.owner && <CogPending " in pv)
    check("its one request is the same-origin root, POST /api/cog/orgs, and nothing else is fetched by hand",
          re.findall(r"\bfetch\(([^,)]*)", n) == ["'/api/cog/orgs'"] and "method: 'POST'" in n, str(re.findall(r"\bfetch\(([^,)]*)", n)))
    m = re.search(r"export const NEW_ORG_KEY = /(.+?)/\n", n)
    kre = re.compile(m.group(1)) if m else None
    check("the client's key rule is the server's: [a-z][a-z0-9-]{1,30}",
          bool(kre) and all(kre.search(k) for k in ("lab", "a1", "ops-2")) and not any(
              kre.search(k) for k in ("Lab", "1lab", "l", "a" * 32, "lab.x", "-lab", "la b")))
    check("no hex colour; the pending room is a promise with seed's face and a still frame under reduced motion",
          not re.findall(r"#[0-9a-fA-F]{3,8}\b", n) and "seed is building" in no.read_text()
          and 'AgentFace name="seed"' in n and "useReducedMotion()" in n)
    check("the sheet is portalled, and every phase has its words (asking, refused in the server's words, done)",
          "createPortal(" in n and "Asking seed…" in no.read_text() and "seed has it" in no.read_text()
          and "j.error ??" in n)

    print("\nK5 THE FLOOR CENTRES ON THE FOCUSED ORG")
    fl = (SRC / "components" / "FloorView.tsx").read_text()
    m = re.search(r"const fit = \(min = 0, whole = false\) => \{(.*?)\n  \}", fl, re.S)
    body = m.group(1) if m else ""
    # the focused room's own centre is its SLOT's (the conglomerate puts it first, siblings collapsed beside it): one
    # org, one slot one.w wide, so slots[me].cx is one.w / 2, exactly one.w * me + one.w / 2 with me = 0
    check("fit() centres on the focused room (its slot's centre) at one room's scale unless asked for the whole",
          "const w = whole ? room.w : one.w" in body and "whole ? room.w / 2 : slots[me].cx" in body
          and "x: size.w / 2 - cx * k" in body, body[:300])
    check("the first framing is the focused room; only the ⤢ control frames the whole floor",
          "fit(0.6)\n" in fl and "() => fit(0, true)]" in fl and fl.count("fit(0, true)") == 1)

    print("\nK6 THE CONGLOMERATE: FOCUS, FLOOR, NETWORK")
    flp, nw = SRC / "components" / "FloorView.tsx", SRC / "components" / "NetworkView.tsx"
    f, w, cg = code(flp.read_text()), code(nw.read_text()), src["cog"]
    fn = re.search(r"export function chooseOrg\(org: string\) \{(.*?)\n\}", cg, re.S)
    body = fn.group(1) if fn else ""
    check("a focus switch sets the cookie BEFORE the reload, keeps the URL (the open tab), and never prompts for a key",
          bool(fn) and 0 <= body.find("document.cookie =") < body.find("location.reload()")
          and "location.href" not in body and "location.hash" not in body and "obs_key" not in body, body[:300])
    check("a room is locked only when it REFUSED the key (401/403), never when it is down or slow",
          "[401, 403].includes(" in cg and "locked: agents.status === 'rejected'" not in cg)
    check("the cross-org ties are read through the focused base (safeBase-checked roomGet), owner route /influence/cross",
          "roomGet<Cross>(focusBase(), '/influence/cross')" in cg)
    check("FLOOR one org: one slot, one.w wide (the room as before); the focused room is first, so nothing in it moves",
          "const order = [me, ...rooms.map((_, i) => i).filter(i => i !== me)]" in f
          and "const w = i === me ? one.w :" in f and "const cx = slots[me].cx" in f)
    check("FLOOR a sibling is collapsed: its people get seats only when it is the open one; hover previews, Esc closes",
          re.search(r"out\[`@org:\$\{r\.name\}`\] = \{ x: scx, y: cy \}\s*if \(r\.name !== open\) return\s*const sr = seatRing", f) is not None
          and "setPeek(r.name)" in f and "if (e.key === 'Escape') setOpen(null)" in f)
    check("FLOOR the sibling's orb casts no glow (RoomOrb), its people ring without the 28px halo; Focus walks in",
          "<RoomOrb size={64}" in f and (lambda t, a, b: 0 < t.find(a) < t.find(b) and "0 0 28px -4px" not in t[t.find(a):t.find(b)])(
              flp.read_text(), "the cog's other rooms", "you, the owner")   # raw text: the markers are JSX comments
          and "const focusIt = () => r.org && chooseOrg(r.org)" in f)
    check("FLOOR a sibling's peers row is a room, never a rim peer; ties drawn only in a cog with traffic",
          "allPeers.filter(p => !sibs.some(r => r.name === p.org))" in f and "{cross.length > 0 && mode !== 'live' && (" in f)
    check("NETWORK a sibling is collapsed to its orb (RoomOrb), opened in place, one at a time, Esc or the pane closes it",
          "<RoomOrb size={52}" in w and "setOpenSib(isOpen ? null : o.name)" in w and "onPaneClick={() => setOpenSib(null)}" in w
          and "if (e.key === 'Escape') setOpenSib(null)" in w and "if (!isOpen) return" in w)
    check("NETWORK opening a sibling never remounts the map (its people are not in the layout key)",
          "flow.nodes.filter((n) => !n.id.startsWith('sib:'))" in w)
    sib_at, own_at = w.find("const sib = sibOf(flash.from_org) ?? sibOf(flash.to_org)"), w.find("} else if (who.owner) {")
    check("NETWORK a sibling's message is placed BEFORE the owner branch (its seed never lights ours) on the sibling edge",
          0 <= sib_at < own_at and "`peer:${sib}`" in w)
    check("NETWORK the org <-> sibling edge is weighted by the ties, and agent <-> agent ties are drawn when it is open",
          "const cogTies = useMemo(() => ties(cross, sibNames)" in w and "id: `e-tie-${t.here}-${o.name}-${t.there}`" in w)
    return 1 if fails else 0


if __name__ == "__main__":
    rc = main()
    print()
    if rc == 1:
        print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    elif rc == 0:
        print("observatory cog UI: one building, the key only to safe bases, one org as before")
    sys.exit(rc)
