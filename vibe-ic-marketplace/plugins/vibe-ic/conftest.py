# BACKLOG-v13 Wave 6 (v0.119.38). pytest discovery fix:
#
# When pytest is invoked from the marketplace root
# (`cd vibe-ic-marketplace && pytest -q`) the plugin's own
# pytest.ini is no longer the configfile, so the implicit
# rootdir-on-path behaviour that lets
#
#   from programs.host_soft_reset_unwake_path_check import main
#
# resolve in plugins/vibe-ic-d/tests/* no longer applies. This
# conftest.py prepends the plugin's `programs/` directory to
# sys.path during pytest collection so those imports keep working
# regardless of which CWD pytest was launched from.
#
# This file is a no-op for plugins/vibe-ic-d/programs/tests/*, which
# import via `from <module> import ...` — it just adds the same
# directory to sys.path, which is harmless.
import sys
from pathlib import Path

import pytest

# vibe-ic#1417 — the half of that issue no source-shape check could ever fix,
# because the writer is not a test module.
#
# `test_issue1417_no_test_bytecompiles_the_shipped_tree.py` enforces that no
# byte-code appears under `skills/`, and EVERY test module in this tree obeys
# it. The guard was red anyway in any session that collects a skills tier,
# because the writer is PYTEST'S OWN assertion-rewrite cache, deposited at
# COLLECTION time — before a single test in the session has run:
#
#     pytest skills/ams-sim/tests/test_compliance.py <the guard>
#       -> byte-code is present in the shipped skills/ tree:
#          ['skills/ams-sim/tests/__pycache__/
#            test_compliance.cpython-310-pytest-9.0.3.pyc']
#     the same guard ALONE: passes
#
# `run_tests.sh:96` hands every tier — `skills/*/tests` among them — to ONE
# `python3 -m pytest`, so THE FULL SUITE IS GUARANTEED to write into the tree
# it ships, and so is any targeted selection that happens to include one of
# those files. Nothing was ever committed: `git ls-files -- '*.pyc'` is empty.
# The gate was telling the truth about the working tree, and the defect it was
# reporting lived in the runner, not in it — so the check is not narrowed and
# not skipped; the write is stopped.
#
# IT BELONGS HERE for the reason this file already gives twice below: the
# rootdir conftest rides EVERY pytest invocation rooted at the plugin —
# `run_tests.sh`, a bare `pytest`, and the targeted subset
# `tools/gatekeeper-land.sh` runs on every landing — so it cannot be missed by
# choosing a path filter, and it executes before collection, which is when the
# write happens. It is also the setting the hermetic landing runner ALREADY
# imposes on its whole session via `PYTHONDONTWRITEBYTECODE=1`, so this closes
# a split between the landing lane and every other lane rather than inventing a
# rule. MEASURED COST — one worktree, one 72-file selection (4 programs/tests
# files + all 68 `skills/*/tests`), caches cleared before each arm, this LINE
# the only difference: 39.22 s without it, 39.68 s with it, and the second arm
# also runs to completion two tests the first fails early. Inside the noise.
#
# ONE RESIDUE, STATED rather than glossed: a conftest cannot suppress the
# caching of ITSELF — pytest rewrites and caches `conftest.py` in order to
# import it, before its body can set the flag — so `__pycache__/conftest.*.pyc`
# still appears at this directory. It is one file, it is outside every shipped
# tier, `git status --porcelain` stays empty over it, and
# `test_this_session_cannot_cache_byte_code_beside_a_shipped_source` pins it so
# its disappearance is something somebody has to look at.
sys.dont_write_bytecode = True

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE / "programs"
if _PROGRAMS.is_dir() and str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
# Also expose the plugin root so `from programs.foo import bar` works.
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# vibe-ic#1029 — "a full suite run on a clean worktree leaves
# `git status --porcelain` EMPTY" was a fact somebody had to REMEMBER to check.
# Three writers into the shipped tree were each found by accident, never by
# looking. Loading the guard HERE — the rootdir conftest, above both test trees
# — is what makes the rule execute instead of being remembered: it rides every
# pytest invocation rooted at the plugin, which includes the targeted subset
# `tools/gatekeeper-land.sh` runs on EVERY landing.
#
# It is deliberately not a CI workflow step: Actions is disabled for this
# account (`.github/workflows-disabled/README.md`), so a guard wired there
# would never run — and a test that is always skipped is the exact defect
# #1029 is about. Session mode costs two `git status` calls (0.20 s measured).
# vibe-ic#1128 — the same reasoning one tier down. `suite_write_guard`
# above stops a run LYING ABOUT WHAT IT WROTE; `not_verified_tier` stops it
# lying about WHAT IT VERIFIED. Measured on the six files #1128 names: with
# the EDA image unreachable, 13 tests move from `passed` to `skipped` and rc
# stays 0 in both arms. Loaded HERE for the same reason as its sibling — the
# rootdir conftest rides every pytest invocation rooted at the plugin,
# including the targeted subset `tools/gatekeeper-land.sh` runs on EVERY
# landing, so the disclosure cannot be missed by choosing a path filter.
# vibe-ic#1446 — the third tier, and the same argument a third time.
# `suite_write_guard` stops a run lying about WHAT IT WROTE; `not_verified_tier`
# stops it lying about WHAT IT VERIFIED; `scratch_root_guard` stops it lying
# about WHAT IT MEASURED. A suite whose scratch root sits inside a git work tree
# reports 46 failures that are the ROOT, not the tree — measured on 75776dbbb,
# same commit, same host, one pytest invocation each, only `--basetemp` moved:
# 86 passed outside a repository, 46 failed + 40 passed inside. Every one of
# those 46 names its own subject instead of the cause, so the cause is nowhere
# in the output. #1446 published five counts of main's redness — ~93, 46, 39,
# 145, 218 — and four were retracted or corrected by their own author; the
# largest single correction was exactly this. The guard DECLARES the scratch
# root on every run and REFUSES a run it would falsify. Riding the rootdir
# conftest is what makes that execute rather than be remembered, and it costs
# one `git rev-parse` per session.
pytest_plugins = ("suite_write_guard", "not_verified_tier", "scratch_root_guard")


# ORGANIC #574 — robust waveform-artifact hygiene. Many tests run `vvp` on an
# official benchmark testbench that carries `$dumpfile("wave.vcd")`; when such a
# vvp runs with cwd inherited (the plugin tree under pytest) it leaves a stray
# wave.vcd that the waveform-hygiene gate (test_v0_3_38) flags — and whether it
# flags depends on TEST ORDER (a leaker after the gate passes that run, a leaker
# before it FAILs). Root-cause fixes pin the known leakers to cwd=tempdir; this
# autouse fixture is the order-independent safety net: after EVERY test it removes
# any stray waveform dump from the 3 spots vvp can land one (the test's cwd, the
# plugin root, programs/). Cheap (a few unlink calls), general (catches any future
# leaker too), and never touches a committed file (all such dumps are gitignored).
_WAVE_SUFFIXES = (".vcd", ".fst", ".ghw", ".shm")


@pytest.fixture(autouse=True)
def _strip_stray_waveform_artifacts():
    yield
    spots = {_HERE, _PROGRAMS}
    try:
        spots.add(Path.cwd())
    except OSError:
        pass
    for spot in spots:
        try:
            for f in spot.iterdir():
                if f.is_file() and f.suffix in _WAVE_SUFFIXES:
                    f.unlink(missing_ok=True)
        except (OSError, FileNotFoundError):
            pass
