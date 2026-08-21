"""The NOT_VERIFIED tier, and the rule that keeps it from rotting. vibe-ic#1128.

WHAT IS ASSERTED HERE, AND WHY EACH ONE EARNS ITS PLACE
=======================================================
The defect vibe-ic#1128 measured is that a test which could not reach the EDA
image is filed under `skipped`, and `skipped` is green. Three things have to
hold for the repair to mean anything, and each has its own failure mode:

1. **A declared non-verification is SEEN.** If the sentinel did not survive the
   round trip through pytest's report object, the summary block would be empty
   on exactly the runs it exists for and nobody would notice — the reporting
   equivalent of the silent skip.
2. **The refusal actually refuses.** A tier that can be switched to blocking and
   then still exits 0 is lie-shape #7 — wired where it can never block.
3. **A NEW skip site cannot forget to join.** This is the one that decides
   whether the fix survives contact with the next author. Eleven sites were
   converted; the twelfth, written six months from now by someone who has never
   read this file, is the whole risk. So the corpus is walked with the AST and
   an undeclared infrastructure-shaped skip is a FAILURE, not a lint note.

THE ROT GUARD'S SUBJECT, STATED NARROWLY ON PURPOSE
===================================================
It fires only on a skip whose reason names the EDA image, a container, docker,
or a path inside the image (`/foss`). It deliberately does NOT fire on
`iverilog not on host` (`test_synth_frontend_shared.py:287,334`), which is the
same SHAPE — a verification that did not happen — but a different provisioning
question and outside vibe-ic#1128's measurement. Naming that exclusion here is
the point: an unstated exclusion is how a guard's real coverage drifts away
from its apparent coverage.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import not_verified_tier as NV  # noqa: E402

TESTS_DIR = Path(__file__).resolve().parent
PLUGIN = TESTS_DIR.parents[1]

#: Tokens that make a skip reason an INFRASTRUCTURE-ABSENT one. Quoted from the
#: eleven reasons vibe-ic#1128 measured, not invented.
_INFRA_TOKENS = ("vibeic-eda", "eda image", "/foss", "docker", "container")

#: The one shape excluded by name; see the module docstring.
_EXCLUDED = ("iverilog",)

#: Functions in `not_verified_tier` that stamp the SENTINEL onto a reason
#: STRING (as opposed to raising the skip). A `skipif` that calls one of these
#: is declared.
_DECLARERS = ("not_verified_reason", "probe_skip_reason")


def _run_probe(tmp_path, body: str, env_extra=None):
    """Run a one-file pytest session that uses the tier, return the result."""
    test = tmp_path / "test_probe.py"
    test.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(PLUGIN / 'programs')!r})\n"
        "from not_verified_tier import skip_not_verified\n"
        + body)
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # `-p not_verified_tier` imports it as a PLUGIN, which goes through
    # `__import__` and therefore needs `programs/` on the child's PYTHONPATH —
    # the parent's `sys.path.insert` above does not cross the process boundary.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PLUGIN / "programs")]
        + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.pop(NV.REQUIRE_ENV, None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
         "-p", "not_verified_tier", str(test)],
        capture_output=True, text=True, cwd=str(tmp_path), timeout=55, env=env)


# ---------------------------------------------------------------------------
# 1. a declared non-verification is SEEN
# ---------------------------------------------------------------------------
def test_a_declared_non_verification_is_named_in_the_summary(tmp_path):
    res = _run_probe(tmp_path,
                     "def test_x():\n"
                     "    skip_not_verified('the widget is out of reach', 'pull it')\n")
    out = res.stdout + res.stderr
    assert "[NOT VERIFIED]" in out, out
    assert "the widget is out of reach" in out, out
    assert "remedy: pull it" in out, (
        "the remedy is part of the contract — an anchor bump's whole fix is "
        f"'pull this tag', and a report that omits it is half an answer\n{out}")


def test_an_ordinary_skip_is_not_claimed_by_this_tier(tmp_path):
    """The tier must not annex every skip. 44 skips repo-wide are genuine N/A."""
    res = _run_probe(tmp_path,
                     "import pytest\n"
                     "def test_x():\n"
                     "    pytest.skip('nothing to verify on this platform')\n")
    out = res.stdout + res.stderr
    assert "[NOT VERIFIED]" not in out, (
        f"an ordinary N/A skip was reported as a non-verification\n{out}")
    assert res.returncode == 0, out


def test_a_passing_run_prints_no_block_at_all(tmp_path):
    res = _run_probe(tmp_path, "def test_x():\n    assert True\n")
    out = res.stdout + res.stderr
    assert "[NOT VERIFIED]" not in out, out
    assert res.returncode == 0, out


# ---------------------------------------------------------------------------
# 2. the refusal actually refuses — and says so when it does not
# ---------------------------------------------------------------------------
def test_reporting_mode_is_green_and_announces_that_it_is_not_blocking(tmp_path):
    res = _run_probe(tmp_path,
                     "def test_x():\n    skip_not_verified('out of reach')\n")
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert "is not set" in out and "NOT blocking" in out, (
        "a guard that is switched off and does not SAY it is switched off is "
        f"the vacuous pass this repo keeps removing\n{out}")


def test_blocking_mode_fails_the_session(tmp_path):
    res = _run_probe(tmp_path,
                     "def test_x():\n    skip_not_verified('out of reach')\n",
                     {NV.REQUIRE_ENV: "1"})
    out = res.stdout + res.stderr
    assert res.returncode != 0, (
        f"{NV.REQUIRE_ENV}=1 did not make an unanswered question fail the "
        f"session — the tier is wired where it can never block\n{out}")
    assert "REFUSES to be green" in out, out


def test_blocking_mode_leaves_a_clean_run_green(tmp_path):
    """The paired half: blocking must cost nothing where verification happened."""
    res = _run_probe(tmp_path, "def test_x():\n    assert True\n",
                     {NV.REQUIRE_ENV: "1"})
    assert res.returncode == 0, res.stdout + res.stderr


def test_blocking_does_not_overwrite_a_real_failure(tmp_path):
    """A failing session keeps its own status: 'the tests failed' is the more
    specific statement, and this tier must not paint over it."""
    res = _run_probe(tmp_path,
                     "def test_fails():\n    assert False\n"
                     "def test_y():\n    skip_not_verified('out of reach')\n",
                     {NV.REQUIRE_ENV: "1"})
    out = res.stdout + res.stderr
    assert res.returncode == 1, f"expected pytest's own rc 1, got {res.returncode}\n{out}"


# ---------------------------------------------------------------------------
# 3. THE ROT GUARD — a new site cannot forget to join
# ---------------------------------------------------------------------------
def _skip_reason_text(node: ast.AST) -> str:
    """Flatten the literal text of a skip reason, f-strings included."""
    chunks = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            chunks.append(sub.value)
    return " ".join(chunks).lower()


def _undeclared_infra_skips():
    """Every `pytest.skip`/`skipif` in the corpus that names infrastructure and
    did NOT come through the tier. Returns ``[(relpath, lineno, reason)]``."""
    out = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except SyntaxError:                                # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else getattr(fn, "id", ""))
            if name not in ("skip", "skipif"):
                continue
            # A `skipif` whose reason is built by one of the tier's reason
            # builders IS declared — the stamp is applied inside a nested call,
            # so the flat string walk below would otherwise re-flag a converted
            # site. `probe_skip_reason` joined the list in vibe-ic#1283: it is
            # `not_verified_reason` plus the PRESENT/ABSENT/UNANSWERED routing,
            # and its output carries the same SENTINEL.
            if any(isinstance(s, ast.Call)
                   and (getattr(s.func, "id", "")
                        or getattr(s.func, "attr", "")) in _DECLARERS
                   for s in ast.walk(node)):
                continue
            reason = _skip_reason_text(node)
            if not any(tok in reason for tok in _INFRA_TOKENS):
                continue
            if any(tok in reason for tok in _EXCLUDED):
                continue
            out.append((path.name, node.lineno, reason[:90]))
    return out


#: The residual this repair did NOT convert, per file, MEASURED 2026-08-12 with
#: the detector below on `origin/main` @ `94754771` after converting the eleven
#: sites vibe-ic#1128 names: **48 sites across 25 files**.
#:
#: WHY A RESIDUAL AND NOT A CLEAN SWEEP. #1128 measured six files and eleven
#: sites; the detector says the shape is four times more common than the issue
#: that found it knew. Converting all 48 blind is the change most likely to be
#: wrong: each needs the RIGHT remedy, several are ngspice/iverilog/LEC probes
#: whose reason merely mentions a container, and a wrong remedy is worse than
#: none — it sends a reader to a command that does not fix their run.
#:
#: SO THIS IS A RATCHET, NOT AN ALLOWLIST, and the distinction is the whole
#: point. A NEW undeclared site FAILS — the frontier cannot grow. An entry here
#: may only be DELETED, never edited upward, and the total below is asserted
#: exactly, so converting a file without removing its line is also a failure.
#: Same shape as `gate_skip_routing_check`'s drained inventory.
#:
#: 2026-08-15 (vibe-ic#1283): `test_analog_a3_netlist_emit.py` and
#: `test_v1_4_observable_capability_probes.py` were converted while their
#: probes were made tri-state, so their entries are DELETED per the rule above.
#: `test_v1_3_52_r6_sparse_die_welltie.py` keeps its 1 on purpose: its probe is
#: now declared, but the site also carries a second, ORDINARY mark — "the live
#: proof was not requested" — and annexing an opt-in N/A into this tier is the
#: over-reach the module docstring rules out.
RESIDUAL_UNDECLARED: dict = {
    "test_fault_atpg_run.py": 1,
    "test_formal_env_unavailable_actionable.py": 1,
    "test_gds_geometry_signoff_wiring.py": 1,
    "test_hspice_lib_ngspice_normalize.py": 1,
    "test_issue193_custom_pdk_primary_selection_ngspice.py": 1,
    "test_lec_include_hub_aggregator.py": 2,
    "test_lec_post_layout_check.py": 1,
    "test_lec_run.py": 6,
    "test_phase3_routability_driven_placement.py": 1,
    "test_reset_alias_tri0_driven_reset_port_bug.py": 2,
    "test_score_cocotb_functional_verdict_parser.py": 2,
    "test_staged_macro_aware_synth_define.py": 1,
    "test_v1_0_52_gap1_via_analyzer_sky130_unnumbered_cut.py": 1,
    "test_v1_0_78_issue729_ppa_area_threshold.py": 4,
    "test_v1_0_80_issue739_ppa_unreachable_target_escape.py": 7,
    "test_v1_0_83_issue756_ppa_disjunctive_clauses.py": 1,
    "test_v1_0_85_issue768_ppa_reachability_submission_independent.py": 2,
    "test_v1_0_85_issue769_ppa_generic_meets_target.py": 2,
    "test_v1_0_86_issue771_ppa_metric_window.py": 1,
    "test_v1_3_52_r6_sparse_die_welltie.py": 1,
    "test_v1_3_83_fork_iverilog_escalation.py": 1,
    "test_v1_3_85_chip_top_vl_tri_outermost.py": 4,
    "test_v1_3_88_issue119_chip_top_reemit_pull_restore.py": 2,
}


def test_no_new_undeclared_infrastructure_skip_appears():
    """The rule that decides whether this repair survives the next author.

    An infrastructure-shaped `pytest.skip` that did not go through
    `not_verified_tier` is invisible to the roll-up again — one new site and
    the run is quietly back to reporting an unanswered question as a pass. The
    frontier may only shrink.
    """
    seen: dict = {}
    for fname, _ln, _r in _undeclared_infra_skips():
        seen[fname] = seen.get(fname, 0) + 1

    new_files = sorted(set(seen) - set(RESIDUAL_UNDECLARED))
    assert not new_files, (
        "NEW file(s) carry an undeclared infrastructure-absent skip — a "
        "verification that will not happen and will not be reported as such "
        "(vibe-ic#1128):\n"
        + "\n".join(f"    {f} ({seen[f]} site(s))" for f in new_files)
        + "\nUse `skip_not_verified(reason, remedy)`, or "
          "`not_verified_reason(...)` inside a `skipif`.")

    grew = sorted(f for f in seen
                  if f in RESIDUAL_UNDECLARED
                  and seen[f] > RESIDUAL_UNDECLARED[f])
    assert not grew, (
        "the undeclared residual GREW in:\n"
        + "\n".join(f"    {f}: {RESIDUAL_UNDECLARED[f]} -> {seen[f]}" for f in grew)
        + "\nThis inventory is a ratchet: entries are deleted as they are "
          "converted, never raised.")

    shrunk = sorted(f for f in RESIDUAL_UNDECLARED
                    if seen.get(f, 0) < RESIDUAL_UNDECLARED[f])
    assert not shrunk, (
        "these files now carry FEWER undeclared sites than the inventory "
        "records, which is good — delete/lower their entries so the number "
        "keeps meaning something:\n"
        + "\n".join(f"    {f}: {RESIDUAL_UNDECLARED[f]} -> {seen.get(f, 0)}"
                    for f in shrunk))


def test_the_rot_guard_can_actually_fire(tmp_path):
    """The guard's own paired control.

    A scanner that matched nothing would pass the test above forever while the
    corpus filled with undeclared sites. This plants one and shows the detector
    sees it, using the same function the real assertion uses.
    """
    planted = TESTS_DIR / "test_zz_not_verified_rot_probe.py"
    planted.write_text(
        "import pytest\n"
        "def test_planted():\n"
        "    pytest.skip('vibeic-eda container not available')\n")
    try:
        found = _undeclared_infra_skips()
    finally:
        planted.unlink(missing_ok=True)
    assert any(f == planted.name for f, _ln, _r in found), (
        "the rot guard did not see a planted undeclared infrastructure skip, "
        f"so it is a ban rather than a check. Saw: {found}")


def test_the_declared_sites_are_not_seen_as_undeclared():
    """The reverse: converting a site must actually silence the guard, or the
    two halves disagree and one of them is wrong."""
    converted = TESTS_DIR / "test_synth_frontend_shared.py"
    assert "skip_not_verified(" in converted.read_text(), (
        "the converted file no longer routes through the tier; the eleven "
        "sites of vibe-ic#1128 have drifted back")
    assert not any(f == converted.name for f, _ln, _r in _undeclared_infra_skips())
