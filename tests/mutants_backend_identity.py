"""Authored mutants for observatory/api/main.py's half of plan-11859 U1+U2 (D2, a2 I1): each is a backend that lets a
signed identity open more than its own members row gives it, or ignores it. Every one must be CAUGHT by
tests/test_cog_signin.py.

    venv/bin/python devtools/mutation_probe.py tests/mutants_backend_identity.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUBJECT = REPO / "observatory" / "api" / "main.py"
ORACLE = REPO / "tests" / "test_cog_signin.py"
ENV = "OBS_MAIN_SRC"

MUTANTS = {
    "B1 the handlers' predicate ignores the signed-in owner (the key alone, as before U1+U2)":
        ('    return (bool(OBS_KEY) and request.headers.get("x-obs-key", "") == OBS_KEY) or _signed_owner(request)',
         '    return bool(OBS_KEY) and request.headers.get("x-obs-key", "") == OBS_KEY'),
    "B2 any role is the owner (a member of B opens B's owner routes)":
        ('    return getattr(request.state, "role", None) == "owner"', '    return getattr(request.state, "role", None) is not None'),
    "B3 the role is not read from this org's members (every verified identity is an owner)":
        ('    return uid, await pool.fetchval("SELECT role FROM members WHERE uid = $1", uid)', '    return uid, "owner"'),
    "B4 the gate judges before it reads the identity":
        ("    request.state.uid, request.state.role = await _who(request)", "    request.state.uid, request.state.role = None, None"),
    "B5 the event stream ignores the signed-in owner (an EventSource can only send the cookie)":
        ('    owner = (bool(OBS_KEY) and request.query_params.get("key", "") == OBS_KEY) or _signed_owner(request)',
         '    owner = bool(OBS_KEY) and request.query_params.get("key", "") == OBS_KEY'),
    "B6 the verifier accepts any org's token (aud = None checks nothing: the token's own aud is taken)":
        ("    uid = _identity.verify(tok, _keys(), _AUD)\n", "    uid = _identity.verify(tok, _keys(), _identity.json.loads(_identity._unb64(tok.split('.')[0])).get('aud'))\n"),
    "B7 the backend's Set-Cookie pipe passes every cookie (its own relay to canvas)":
        ("    resp.raw_headers = _relay.response_headers(r.headers.raw, orgs.name())", "    resp.raw_headers = list(r.headers.raw)"),
    "B8 a members lookup that fails is a 500 (an org whose schema.sql isn't re-applied breaks its public face)":
        ("    except (asyncpg.PostgresError, OSError) as e:   # no members table yet", "    except ZeroDivisionError as e:   # no members table yet"),
}
