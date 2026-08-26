#!/usr/bin/env python3
"""legend_guard — the economy heat-definition drift guard (goal 3408, enforcement half).

Catches the CLASS abstractor-1 found on the org tool surface (plan-3408 #16134): a LIVE
surface computing heat Q by subtracting the budget-sum W (a PRICE, Σ budget_tokens) from
flux Φ (a COST, billable tokens) — unit-mixed, goes negative when shipped-goal budgets
exceed window flux, the economy.md "Φ = W-attributable + Q" folklore read literally.

THE AUTHORITY (nucleus/econ.py thermo): Q = Φ − phi_goal_attributed — BOTH flux, never
negative. So the rule: heat is a SAME-BASE difference. Any subtraction that mixes a flux
quantity with a budget quantity is a unit error and is flagged; and any value NAMED as
heat/Q, computed by subtraction, whose subtrahend is not a flux quantity is flagged
fail-closed (an unrecognised subtrahend for heat defaults to a violation, never to OK).

WHY AST, NOT GREP — the load-bearing choice. A lexical `phi - W` scan false-positives on
the fix's OWN corrective comment ("NOT phi - W", server.py:127) and on the rendered label
string ("first law: Φ = W-attributable + Q"). Comments and string literals are not in the
AST, so this scans ONLY what executes — the "check what RUNS, not what is written about it"
law this org keeps re-learning (an oracle that failed on its own comment; a check that
passed because a comment named the right function).

Independence: the guard does not import econ.py or the org server; it re-derives the
same-base rule from the SPEC, so it cannot pass by sharing the emitter's code.

CLI:  python nucleus/legend_guard.py [--verbose]   → exit 0 clean, 1 on any violation.
Lib:  scan_source(code, name) -> list[Violation]   (used by tests/test_legend_guard.py).
"""
from __future__ import annotations
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Surfaces that may COMPUTE the economy's heat. Roots are scanned; a file is examined only
# if it actually references a heat/flux term (cheap pre-filter), so this is a derivation,
# not a frozen who-may-skip manifest. econ.py is INCLUDED — the authority must hold itself
# to its own definition.
SURFACE_ROOTS = ("mcp", "nucleus", "observatory/api")
_TERMS = ("phi_goal_attributed", "thermo", '"Q"', "'Q'", "heat", "phi", "flux")

# ── base classification: every name/expr in an economy surface is flux, budget, or unknown.
# flux = a COST (billable tokens); budget = a PRICE (Σ budget_tokens). Heat is flux−flux.
# the goal-attributed FLUX — Q's ONE allowed subtrahend. Both the thermo key and the
# conventional local short-names the surfaces bind it to (server.py: `phi_goal`), so a
# correctly-sourced subtrahend is recognised by name even without an in-scope binding.
# Kept TIGHT: a genuine unknown (e.g. `mystery`) stays unknown and fails closed.
FLUX_ATTRIBUTED_KEYS = {"phi_goal_attributed", "phi_goal", "attributed_flux", "goal_attributed_flux"}
FLUX_KEYS = {"phi", "flux", "bill", "billable", "phi_heat", "heat_instant_phi", "tokens_out"}
BUDGET_KEYS = {"w", "budget", "budgets", "budget_tokens", "work"}   # the PRICE — never a heat subtrahend

FLUX = "flux"
FLUX_ATTR = "flux_attr"
BUDGET = "budget"
UNKNOWN = "unknown"

HEAT_NAMES = {"q", "heat", "q_heat", "heat_phi"}        # names/keys that denote a heat OUTPUT


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}  {self.detail}"


def _key_base(key: str) -> str:
    k = key.lower()
    if k in FLUX_ATTRIBUTED_KEYS:
        return FLUX_ATTR
    if k in FLUX_KEYS:
        return FLUX
    if k in BUDGET_KEYS:
        return BUDGET
    return UNKNOWN


def _string_arg(node: ast.AST) -> str | None:
    """The literal string a th.get('X') / th['X'] / dict key reads, if any."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class _Scope:
    """Per-function name→base map, built from the bindings the function actually makes."""

    def __init__(self) -> None:
        self.base: dict[str, str] = {}

    def classify(self, node: ast.AST) -> str:
        """Base of an expression node: trace bound names, th[...] reads, and bare names."""
        if isinstance(node, ast.Name):
            return self.base.get(node.id, _key_base(node.id))
        # th.get("phi_goal_attributed")  /  m["W"]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args:
            s = _string_arg(node.args[0])
            if s is not None:
                return _key_base(s)
        if isinstance(node, ast.Subscript):
            s = _string_arg(node.slice)
            if s is not None:
                return _key_base(s)
        # int(x) / round(x, n) / a wrapping call → base of the first arg
        if isinstance(node, ast.Call) and node.args:
            return self.classify(node.args[0])
        if isinstance(node, ast.Tuple) and node.elts:
            return UNKNOWN
        return UNKNOWN

    def bind_targets(self, targets: list[ast.AST], value: ast.AST) -> None:
        """`a, b, c = th['phi'], th['W'], th['phi_goal_attributed']` and single binds."""
        names = [t for t in targets if isinstance(t, ast.Name)]
        # tuple-unpack: element-wise
        if len(names) == 1 and isinstance(names[0], ast.Name) is False:
            return
        for t in targets:
            if isinstance(t, ast.Tuple) and isinstance(value, ast.Tuple) \
                    and len(t.elts) == len(value.elts):
                for tt, vv in zip(t.elts, value.elts):
                    if isinstance(tt, ast.Name):
                        self.base[tt.id] = self.classify(vv)
            elif isinstance(t, ast.Name):
                self.base[t.id] = self.classify(value)


def _heat_named(target: ast.AST) -> bool:
    if isinstance(target, ast.Name):
        return target.id.lower() in HEAT_NAMES
    if isinstance(target, ast.Subscript):
        s = _string_arg(target.slice)
        return s is not None and s.lower() in HEAT_NAMES
    return False


def scan_source(code: str, name: str = "<source>") -> list[Violation]:
    """Return every unit-mixed / fail-closed heat-subtraction violation in `code`."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [Violation(name, e.lineno or 0, f"unparseable — a check that cannot read its subject FAILS: {e.msg}")]

    out: list[Violation] = []

    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] + [tree]:
        scope = _Scope()
        # first pass: bindings (module/function body, in order)
        for stmt in ast.walk(func):
            if isinstance(stmt, ast.Assign):
                scope.bind_targets(stmt.targets, stmt.value)

        # second pass: every subtraction, judged in this scope
        for node in ast.walk(func):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
                lb, rb = scope.classify(node.left), scope.classify(node.right)
                bases = {lb, rb}
                # (1) UNIT MIX: a budget quantity differenced against any flux quantity.
                if BUDGET in bases and (FLUX in bases or FLUX_ATTR in bases):
                    out.append(Violation(name, node.lineno,
                        f"unit-mixed heat: flux − budget-W (bases {lb}−{rb}). Q must be Φ − phi_goal_attributed (flux−flux)."))
                    continue
                # (2) FAIL-CLOSED: this subtraction FEEDS a heat output but its subtrahend is
                # not a recognised flux quantity → default to violation, do not wave through.
                if _feeds_heat(node, func) and rb not in (FLUX, FLUX_ATTR):
                    out.append(Violation(name, node.lineno,
                        f"heat computed with a non-flux subtrahend (base {rb}); heat's subtrahend must be phi_goal_attributed."))
    # de-dup (walk visits nested funcs twice: module walk + func walk)
    seen, uniq = set(), []
    for v in out:
        k = (v.line, v.detail)
        if k not in seen:
            seen.add(k)
            uniq.append(v)
    return uniq


def _feeds_heat(sub: ast.BinOp, func: ast.AST) -> bool:
    """Is this subtraction the value (possibly wrapped in IfExp/BoolOp/Call) of a heat-named
    assignment or dict entry?"""
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and _contains(node.value, sub) and any(_heat_named(t) for t in node.targets):
            return True
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                ks = _string_arg(k) if k is not None else None
                if ks is not None and ks.lower() in HEAT_NAMES and _contains(v, sub):
                    return True
    return False


def _contains(root: ast.AST, target: ast.AST) -> bool:
    return any(n is target for n in ast.walk(root))


def _surface_files() -> list[Path]:
    files: list[Path] = []
    for root in SURFACE_ROOTS:
        base = REPO / root
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if "test" in p.name or "mutant" in p.name:
                continue
            try:
                txt = p.read_text()
            except Exception:
                continue
            if any(t in txt for t in _TERMS):
                files.append(p)
    return files


def main(argv: list[str]) -> int:
    verbose = "--verbose" in argv
    files = _surface_files()
    violations: list[Violation] = []
    for p in files:
        vs = scan_source(p.read_text(), str(p.relative_to(REPO)))
        violations.extend(vs)
    if verbose:
        print(f"legend_guard: scanned {len(files)} economy surface(s)")
    if violations:
        print("legend_guard: HEAT-DEFINITION DRIFT — a live surface mixes flux with budget:")
        for v in violations:
            print(f"  ✗ {v}")
        print("  Q is Φ − phi_goal_attributed (flux − flux); never Φ − W (W is Σ budgets, a price).")
        return 1
    print(f"legend_guard: OK — {len(files)} economy surfaces compute heat same-base (flux−flux)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
