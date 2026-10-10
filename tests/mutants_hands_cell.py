"""Authored mutants for nucleus/hands.py (plan-7862 Hands, S1), run by nucleus/mutation_probe.py.

    venv/bin/python nucleus/mutation_probe.py tests/mutants_hands_cell.py

One per invariant the S1 oracle claims. These need docker and the built images, so the battery is
slow (each mutant runs the full oracle).

NOT AUTHORED, structurally equivalent: dropping sweep()'s namespace FILTER. kill() addresses every
resource by its NAMESPACED name (hands-<ns>-<id>-…), so an unfiltered sweep that reads another
namespace's lease id still only removes names in its own namespace; the foreign container survives
either way (H13 passes under that mutant). The protection is in names(), and it holds by
construction, not by today's data.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SUBJECT = REPO / "nucleus" / "hands.py"
ORACLE = REPO / "tests" / "test_hands_cell.py"
ENV = "HANDS_SRC"
# The full docker oracle takes about 2 minutes, and a mutant that removes the reaper makes H10 poll
# for up to 40s more. 120s (the default) timed K5/K6 out as NOT PROBED.
TIMEOUT = 420

MUTANTS = {
    "K1 a model-API host is allowed into a lease":
        ("        if any(h == d or h.endswith(\".\" + d) for d in MODEL_API_DOMAINS):\n",
         "        if False:\n"),
    "K2 the cell also joins the egress network (a route out that bypasses the proxy)":
        ("    except Exception as e:  # noqa: BLE001 — a half-built lease is torn down",
         "        _docker(\"network\", \"connect\", EGRESS_NET, n[\"cell\"])\n"
         "    except Exception as e:  # noqa: BLE001 — a half-built lease is torn down"),
    "K3 the profile is a named VOLUME, not tmpfs (survives the container)":
        ('"--tmpfs", "/profile:rw,size=512m,uid=10001,mode=0700",',
         # Labelled with the run's namespace so the oracle's label teardown removes it: an
         # unlabelled `-v hands-profile-<id>` left 9 persistent profiles behind (a2 #42057).
         '"--mount", f"type=volume,src={n[\'cell\']}-profile,dst=/profile,"\n'
         '                f"volume-label=astryx.hands.ns={NS}",'),
    "K4 the generated filter allows every host":
        ('    return "".join(f"^{re.escape(h)}$\\n" for h in allow)', '    return ".*\\n"'),
    "K5 the lease outlives its step cap by one":
        ("    if used >= cap:                                   # the lease dies AT its step cap",
         "    if used > cap:                                    # the lease dies AT its step cap"),
    "K6 no reaper (the wall cap only bites when someone calls)":
        ("    if not reaper:\n        return lease\n", "    return lease\n"),
    "K7 a step doesn't check the deadline (the guard drops it)":
        ("AND steps_used < step_cap AND deadline > now() \"", "AND steps_used < step_cap \""),
    "K11 a step doesn't check the step cap (the guard drops it)":
        ("AND steps_used < step_cap AND deadline > now() \"", "AND deadline > now() \""),
    "K8 kill doesn't remove the cell (the profile isn't wiped)":
        ('    for c in (n["cell"], n["proxy"]):', '    for c in (n["proxy"],):'),
    "K9 every lease shares one network (lease isolation lost)":
        ('    return {"net": f"{base}-net",', '    return {"net": "hands-shared-net",'),

    # The race the oracle caught (H9b): a step-cap refusal that kills the lease aborts the
    # legitimate last step still running. H9c pins it deterministically.
    "K12 a step-cap refusal kills the lease (aborting the last step in flight)":
        ('        raise Refused(f"lease {lease} has used its step cap")',
         '        kill(lease, "step_cap")\n        raise Refused(f"lease {lease} has used its step cap")'),
}
