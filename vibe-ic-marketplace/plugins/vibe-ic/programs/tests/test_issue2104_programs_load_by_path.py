"""vibe-ic#2104 — every program must import when it is loaded BY PATH.

`programs/` is a flat directory whose modules import each other by BARE name.
That resolves for one reason only: running a file as `__main__` puts its
directory on `sys.path`. `importlib.util.spec_from_file_location` does not, so
a bare sibling import raises `ModuleNotFoundError` and the caller measures a
module that never loaded.

MEASURED on 94617408759e by two independent methods that agreed exactly — one
subprocess per file, and the in-process sweep `program_path_load_check`
performs — 470 of the 1385 top-level programs failed: 454 with an unresolved
SIBLING, and 16 more whose `except ImportError:` fell through to a relative
import that cannot work outside a package either.

The named case in the issue is worse than a crash. `lec_equivalence_check`
wraps its sibling import in `try: ... except ImportError:` and substitutes a
stub returning `None` for the structural port-abort classifier. Loaded by path
it went on emitting the FALSE diagnosis that classifier exists to replace,
with nothing in the output saying the classifier was absent.

Both directions here, and — because a gate over a directory can trivially be a
gate that cannot fail — the isolation properties the sweep depends on are
tested as first-class claims, each with the counter-fixture that would pass
without them.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


_SCRIPT = _PROGRAMS / "program_path_load_check.py"

#: The guard the fix installs, in the shape the programs carry it.
_GUARD = (
    "import os as _os\n"
    "import sys as _sys\n"
    "if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:\n"
    "    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))\n"
)








# ---------------------------------------------------------------------------
# 1. THE TREE ITSELF
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2. THE CHECK CAN FAIL — and says which sibling
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# 3. THE ISOLATION THE SWEEP DEPENDS ON
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# 4. WHAT THIS GATE IS NOT ANSWERABLE FOR
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 5. THE NAMED CASE IN THE ISSUE, LOADED BY PATH AND RUN
# ---------------------------------------------------------------------------
_LEC = _PROGRAMS / "lec_equivalence_check.py"


def _load_by_path(path: Path, code: str) -> subprocess.CompletedProcess:
    """Load `path` by `spec_from_file_location` in a child whose `sys.path`
    does NOT contain the programs directory, then run `code` against it."""
    driver = (
        "import importlib.util, os, sys\n"
        f"P = {str(path)!r}\n"
        f"D = {str(path.parent)!r}\n"
        "sys.path[:] = [p for p in sys.path "
        "if os.path.abspath(p or '.') != D]\n"
        "spec = importlib.util.spec_from_file_location('m', P)\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "sys.modules['m'] = m\n"
        "spec.loader.exec_module(m)\n"
        + code
    )
    return subprocess.run([sys.executable, "-c", driver],
                          capture_output=True, text=True, cwd=str(path.parent.parent))


def test_lec_equivalence_check_keeps_the_real_classifier_by_path():
    """On the base tree this printed `False` and the classifier was a stub
    that returns None for every input — the gate then reported the FALSE
    diagnosis it exists to replace, and said nothing about the substitution."""
    r = _load_by_path(_LEC, "print('HAS_GNS', m._HAS_GNS)\n"
                            "print('FROM', m._classify_port_abort.__module__)\n")
    assert r.returncode == 0, r.stderr[-2000:]
    assert "HAS_GNS True" in r.stdout, r.stdout + r.stderr
    assert "FROM lec_gate_netlist_select" in r.stdout, r.stdout


def test_lec_equivalence_check_entry_point_runs_when_loaded_by_path(tmp_path):
    """Importable is not the claim; the entry point has to run. An empty
    project is a state the gate has a verdict for, so a real exit code comes
    back rather than an exception."""
    r = _load_by_path(_LEC,
                      f"rc = m.main([{str(tmp_path)!r}])\n"
                      "print('RC', rc)\n")
    assert r.returncode == 0, r.stderr[-2000:]
    assert "RC " in r.stdout, r.stdout + r.stderr
    rc = int(r.stdout.split("RC ")[1].split()[0])
    assert rc in (0, 1, 2), r.stdout


# ---------------------------------------------------------------------------
# 6. THE IN-PROCESS ENTRY POINTS, DIRECTLY
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 4. THE CHECKER'S OWN IMPORTS MAY NOT SEED THE CHILD  (vibe-ic#2154 / #2175)
# ---------------------------------------------------------------------------
#
# `test_one_program_may_not_repair_the_next` pins the property BETWEEN two
# programs of the subject; these two pin it between the CHECKER and the subject,
# which is a different door into the same room and was open.
#
# MEASURED while making the `--json` write atomic for #2154. The obvious repair
# — `from _atomic_artefact import write_json` at module level, the shape every
# other converted program in this tree uses — was applied and driven over a
# two-program subject holding `_atomic_artefact.py` and one bare import of it:
#
#     module-level import in program_path_load_check  ->  [PASS] rc 0, 0 offenders
#     deferred to the write site                      ->  [FAIL] rc 1, 1 offender
#
# `--one` runs in the same interpreter that has already executed the checker's
# module body, so anything imported up there is in `sys.modules` before
# `load_isolated` snapshots it; the `finally` deletes only what the load ADDED,
# so a pre-seeded sibling survives and every bare import of it in the tree under
# test resolves for free. Removing the directory from `sys.path` cannot help —
# the module object is already there.
#
# Nothing in the file above would have caught it: every fixture sibling here is
# named `a`, `b`, `c` or `_path_layout`, and the checker imports none of those.




# ---------------------------------------------------------------------------
# 5. THE SWEEP READS ITS SUBJECT AND DOES NOT WRITE INTO IT  (vibe-ic#2175)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 6. THE TWO SITES THIS REPAIR TOUCHES, LOADED BY PATH AND *USED*
# ---------------------------------------------------------------------------
#
# `test_every_shipped_program_loads_by_path` above is the population claim, and
# it is the one the BLOCKING gate answers. It is not, on its own, the whole
# claim for a repaired site: it says the module IMPORTED, not that the name the
# bare import bound is the REAL sibling. That distinction is the entire point of
# section 5 — `lec_equivalence_check` imported cleanly by path on the base tree
# and still ran with a stub classifier, because its own `except ImportError`
# swallowed the failure. A repair that put the directory on `sys.path` but bound
# the wrong object would be invisible to a sweep that only counts
# ModuleNotFoundError.
#
# So each site repaired here gets the section-5 treatment: load by path in a
# child whose `sys.path` does NOT contain `programs/`, then CALL through the
# imported name and check the answer only the real sibling can give.
#
# MEASURED on main f91aaa3915, both methods agreeing:
#     [FAIL] landing_hygiene_ratchet_check.py cannot resolve sibling
#            `_atomic_artefact`
#     [FAIL] pad_signal_route_repair.py cannot resolve sibling
#            `phase3_one_shot_runner`
#     [FAIL] program_path_load_check: 2 of 1407 program(s) ...
# Both files are tracked, both are loaded by path, and one of them —
# `landing_hygiene_ratchet_check` — is the program the LANDING itself runs.

_RATCHET = _PROGRAMS / "landing_hygiene_ratchet_check.py"
_PAD_REPAIR = _PROGRAMS / "pad_signal_route_repair.py"
