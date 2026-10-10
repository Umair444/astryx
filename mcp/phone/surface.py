"""astryx · phone surface — WHAT is on the phone's screen, by window, for the tier stamp (plan-8675 C3).

The source is `dumpsys window windows`, not the accessibility dump. Measured on the S0 AVD (android-35): the
default `uiautomator dump` covers the ACTIVE window only (68 nodes, all com.android.settings), so a notification
or a dialog drawn in another window is absent from it while a screenshot shows it. The window list names every
window, its owning package and whether it is visible.

A visible window is PUBLIC only if it matches the public manifest (package + title pattern). Anything else,
including a window this code has never seen, makes the surface PERSONAL: forgetting a window costs visibility in
the org's records, never privacy (a4 #42240 C1's polarity).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "public_manifest.json"
_WIN = re.compile(r"^\s*Window #\d+ Window\{[0-9a-f]+ u\d+ (?P<title>.*)\}:\s*$")
_PKG = re.compile(r"\bpackage=(?P<pkg>\S+)")
_VIS = re.compile(r"\bisVisible=(?P<v>true|false)\b")


def windows(dumpsys: str) -> list[dict]:
    """Every window block in `dumpsys window windows` → {title, package, visible}. A block with no package line
    keeps package=None; a block with no isVisible line counts as VISIBLE (unknown fails toward personal)."""
    out: list[dict] = []
    cur = None
    for line in dumpsys.splitlines():
        m = _WIN.match(line)
        if m:
            cur = {"title": m["title"], "package": None, "visible": None}
            out.append(cur)
            continue
        if cur is None:
            continue
        if cur["package"] is None and (p := _PKG.search(line)):
            cur["package"] = p["pkg"]
        if cur["visible"] is None and (v := _VIS.search(line)):
            cur["visible"] = v["v"] == "true"
    for w in out:
        if w["visible"] is None:
            w["visible"] = True
    return out


def load_manifest(path: Path = MANIFEST) -> list[dict]:
    rules = json.loads(path.read_text())["public_windows"]
    return [{"package": r["package"], "title": re.compile(r["title"])} for r in rules]


def classify(wins: list[dict], manifest: list[dict] | None = None) -> dict:
    """{tier: org|personal, packages: [...], unlisted: [...]} over the VISIBLE windows only."""
    manifest = load_manifest() if manifest is None else manifest
    visible = [w for w in wins if w["visible"]]
    unlisted = [w for w in visible
                if not any(w["package"] == r["package"] and r["title"].fullmatch(w["title"]) for r in manifest)]
    return {"tier": "personal" if unlisted or not visible else "org",
            "packages": sorted({w["package"] or "?" for w in visible}),
            "unlisted": [f'{w["package"]}:{w["title"]}' for w in unlisted]}
