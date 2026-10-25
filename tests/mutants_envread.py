"""Authored mutants for plan-10224 ENVREAD: config.read_env's per-line decode, the migrated readers, and the DERIVED
census (tests/test_envread.py E7). Tree form (each mutant names its file), run by devtools/mutation_probe.py:

    venv/bin/python devtools/mutation_probe.py tests/mutants_envread.py
"""
CF = "src/astryx/config.py"
OR = "tests/test_envread.py"
ORACLE = OR
TIMEOUT = 300

MUTANTS = {
    "V1 the whole file is refused on one bad byte (every key blinded, the DSN too)":
        (CF, '            text = chunk.decode("utf-8")', '            text = raw.decode("utf-8")'),
    "V2 a bad line is decoded with replacement, SILENTLY (no word on stderr)":
        (CF, '        try:\n            text = chunk.decode("utf-8")\n        except UnicodeDecodeError:',
         '        text = chunk.decode("utf-8", "replace")\n        if False:'),
    "V3 the warning prints the bad line (its value leaks to a log)":
        (CF, '            print(f"config.read_env: {p}:{n}: not UTF-8, line skipped"',
         '            print(f"config.read_env: {p}:{n}: not UTF-8, line skipped {chunk!r}"'),
    "V4 the bad line's key is not held absent: its later line is taken in its place":
        (CF, '            if k and k == k.strip() and k not in out and k not in lost:',
         '            if k and k == k.strip() and k not in out:'),
    "V5 the skip is said on stdout, not stderr (a `$(config.py get …)` would swallow it into the value)":
        (CF, '                  + (f" ({k} reads as absent)" if k and k not in out else ""), file=sys.stderr)',
         '                  + (f" ({k} reads as absent)" if k and k not in out else ""))'),
    # the migrated readers: one put back by hand where only the census sees it, one seated src reader reverted
    "R1 a hand-rolled reader is put back in a migrated mcp server (imagegen _key): only the census can see it":
        ("mcp/imagegen/server.py",
         '    v = config.read_env(paths.estate(__file__) / ".env").get("OPENAI_API_KEY")   # the ONE .env reader (plan-10224)\n'
         '    if v is not None:\n        return v\n',
         '    for line in (paths.estate(__file__) / ".env").read_text().splitlines():\n'
         '        if line.startswith("OPENAI_API_KEY="):\n            return line.split("=", 1)[1].strip()\n'),
    "R2 voice_mint's env() hand-parses the .env again (a non-UTF-8 line crashes the voice cap)":
        ("src/astryx/hearing/voice_mint.py",
         '    return config.read_env(paths.estate(__file__) / ".env").get(key, default)   # the ONE .env reader (plan-10224)\n',
         '    f = paths.estate(__file__) / ".env"\n    if f.is_file():\n        for line in f.read_text().splitlines():\n'
         '            if line.startswith(key + "="):\n                return line.split("=", 1)[1].strip()\n'
         '    return default\n'),
    # the census itself: a walk that misses a place, instruments that needn't agree, a stale exemption, a skipped file
    "C1 the census's walk skips a directory (mcp/): a reader planted there is never seen":
        (OR, '    return how, sorted(f for f in rels if not f.startswith("tests/"))',
         '    return how, sorted(f for f in rels if not f.startswith(("tests/", "mcp/")))'),
    "C2 the walk follows no module-level name into a function (ENV = …/.env; ENV.read_text() in a def)":
        (OR, "            if xs is s and after < (x.lineno, x.col_offset) < stop or xs is not s and not self.binds(xs, name):",
         "            if xs is s and after < (x.lineno, x.col_offset) < stop:"),
    "C3 a text-only site (a KEY= parse the walk doesn't read) is never said: the instruments needn't agree":
        (OR, "        for dl in sorted(set(rx) - set(ast_reads)):", "        for dl in []:"),
    "C4 a stale exemption passes silently (a declared reason outlives its site)":
        (OR, "    for k in sorted(set(exempt) - used):", "    for k in []:"),
    "C5 a discarded read_text() is taken for a probe (it decodes, so a non-UTF-8 .env still crashes it)":
        (OR, '                    if p.attr == "read_bytes" and isinstance(self.par.get(gp), ast.Expr):',
         '                    if p.attr in ("read_bytes", "read_text") and isinstance(self.par.get(gp), ast.Expr):'),
    "C6 an unparseable file is skipped, not RED (its reads go uncounted)":
        (OR, '            findings.append((rel, 0, f"unparseable or unreadable ({type(e).__name__}): its .env uses can\'t be "\n'
             '                                     f"classified"))',
         '            pass'),
}
