"""Authored mutants for the sqlguard seal and stamp (plan-11908 D1+D2+D3, a3 review #62830/#62836), tree form, run by
devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_sqlguard_seal.py
"""
EV = "src/astryx/security/sqlguard/evidence.py"
JU = "src/astryx/security/sqlguard/judge.py"
LE = "src/astryx/security/sqlguard/ledger.py"
ORACLE = "tests/test_sqlguard_seal.py"
MUTANTS = {
    "M1 read_sealed skips the sha check (a changed prefix reads as evidence)":
        (EV, "        if len(head) < nb or _sha(head) != h:", "        if len(head) < nb:"),
    "M2 the seal is not cut at the last newline (a partial line is sealed)":
        (EV, '        b = b[:b.rfind(b"\\n") + 1]\n        out.append', "        out.append"),
    "M3 compare compares VOLATILE names":
        (EV, "            a = {k: v for k, v in (a or {}).items() if k not in VOLATILE}", "            a = dict(a or {})"),
    "M4 env_stamp stamps the raw value":
        (EV, "    return {n: (_sha(environ[n].encode())[:16] if n in environ else None) for n in STAMP_ENV}",
             "    return {n: (environ[n] if n in environ else None) for n in STAMP_ENV}"),
    "M5 load_gates reads the whole gates.tsv, not its sealed prefix":
        (JU, '    for line in evidence.read_sealed(d, sl)[0].get("gates.tsv", "").splitlines():',
             '    for line in (open(os.path.join(d, "gates.tsv")).read() if os.path.exists(os.path.join(d, "gates.tsv")) else "").splitlines():'),
    "M6 admit bypasses _report (acts on an unstamped/other-tuple report)":
        (LE, "        raise SystemExit(\"refusing: an admit needs a real reason (it is printed every run)\")\n    rep = _report(trace_dir)",
             "        raise SystemExit(\"refusing: an admit needs a real reason (it is printed every run)\")\n    rep = json.loads((Path(trace_dir) / \"report.json\").read_text())"),
    "M7 shrink bypasses _report":
        (LE, "    path = path or LEDGER\n    rep = _report(trace_dir)", "    path = path or LEDGER\n    rep = json.loads((Path(trace_dir) / \"report.json\").read_text())"),
    "M8 write_report writes no stamp":
        (JU, '        json.dump({**rep, "stamp": st}, f, indent=1, default=sorted)', "        json.dump(rep, f, indent=1, default=sorted)"),
    "M9 a changed seal is not NOT SEARCHED":
        (JU, "    if changed:\n        run_not_searched.append", "    if False:\n        run_not_searched.append"),

    "M12 estate_code_hash covers every estate file (logs/store compared again)":
        (LE, '    return (rel.suffix == ".py" and not', '    return True or (rel.suffix == ".py" and not'),
    "M13 estate_code_hash covers nothing (an edited estate .py is accepted)":
        (LE, '    return (rel.suffix == ".py" and not', '    return False and (rel.suffix == ".py" and not'),
    "M14 the census sees no alias of os.environ":
        (EV, '        alias = {"environ", "env"}\n', '        alias = set()\n'),
    "M15 the closure follows only top-level imports":
        (EV, "        for n in ast.walk(ast.parse(f.read_text(), str(f))):\n            names = []",
             "        for n in ast.parse(f.read_text(), str(f)).body:\n            names = []"),
}
