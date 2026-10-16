"""Mutants for enforce.said(): a hashed absent row's own text, masked then cut (seed #56874, a3 #56878).
The oracle is tests/test_sqlguard_stale_reason.py, which drives the real enforce() on a fabricated report."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUBJECT = REPO / "src" / "astryx" / "security" / "sqlguard" / "enforce.py"
ORACLE = REPO / "tests" / "test_sqlguard_stale_reason.py"
ENV = "ENFORCE_SRC"
MUTANTS = {
    "S1 the hashed line goes back to naming nothing (no ledger text)":
        ('f"a hashed (gitignored-origin) site [{said(rows[key])}]"', '"a hashed (gitignored-origin) site"'),
    "S2 the reason is echoed raw (no mask)":
        ("    r = _PATHISH.sub(mask, str(reason))\n", "    r = str(reason)\n"),
    "S3 gitignored origins are not masked (git is never asked)":
        ('    return r.returncode != 1\n', '    return False\n'),
    "S4 absolute and home-relative paths are trusted to git":
        ('if p[:1] in "~/" or p.startswith("tier/") or ".." in p.split("/"):', 'if p.startswith("tier/") or ".." in p.split("/"):'),
    "S5 everything path-shaped is masked (blanket)":
        ("        private = _private(p)\n", "        private = True\n"),
    "S11 the mask goes back to the RECORDING authority (free text can turn RED into 77)":
        ("        private = _private(p)\n", "        private = p[:1] in \"~/\" or p.startswith(\"tier/\") or ignored(p)\n"),
    "S6 the cut runs before the mask":
        ("    r = _PATHISH.sub(mask, str(reason))\n    r = r if len(r) <= REASON_MAX else r[:REASON_MAX - 1] + \"…\"\n",
         "    r = str(reason)[:REASON_MAX]\n    r = _PATHISH.sub(mask, r)\n"),
    "S7 no cut at all":
        ('    r = r if len(r) <= REASON_MAX else r[:REASON_MAX - 1] + "…"\n', ""),
    "S8 a seed row invents an admitted date":
        ('    if reason == "seed":\n', '    if False:\n'),
    "S9 the red identity carries the reason text":
        ('R(f"R-STALE absent {key}", f"R-STALE {shown}', 'R(f"R-STALE absent {key} {shown}", f"R-STALE {shown}'),
    "S10 the regex drops the ~/ prefix (a stray ~ survives)":
        ('re.compile(r"(?:~/|/)?[\\w.-]+(?:/[\\w.-]*)+")', 're.compile(r"[~/]?[\\w.-]+(?:/[\\w.-]*)+")'),
}
