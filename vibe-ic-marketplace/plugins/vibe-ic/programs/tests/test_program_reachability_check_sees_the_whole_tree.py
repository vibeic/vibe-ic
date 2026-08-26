"""The only instrument that scans every program could not see, could not fail,
and was never run.

`vibe-ic-marketplace/tools/program_reachability_check.py` is the sole auditor
whose population is all 1291 programs; every other wiring instrument covers a
filename-shaped subset (630 / 653 / 208 / 64 / 139, union 707). Three defects
kept it from being usable, and the orphan count went 163 -> 0 without it ever
being consulted:

  SCOPE     its shell venue was `PLUGIN.rglob("*.sh")`, and
            `tools/ci/repo_hygiene_gates.sh` sits at REPO ROOT — the file that
            carried 28 of that campaign's 30 shell closures.
  COST      `_python_files(p)` re-walked the corpus once per program and every
            grep re-scanned every file: ~1291 directory walks and ~5M regex
            searches. It did not finish in ten minutes.
  RULER     it knew no glob dispatcher, so it named all 14 `*_protocol_synth`
            modules unreachable. They are dispatched by
            `phase1_doc_one_shot_runner.py:63803`, which globs them by SHAPE —
            matching the pattern IS the wiring. A gate that always names
            fourteen innocents teaches its reader to discount it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[4] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))


def _mod():
    import program_reachability_check as R
    return R


# ── scope ───────────────────────────────────────────────────────────────────
def test_the_repo_root_shell_lane_is_in_scope():
    """`tools/ci/repo_hygiene_gates.sh` is where the landing lane declares its
    gates, and `tools/gatekeeper-land.sh` executes it. Both were outside the
    PLUGIN-rooted scan, which is why a program wired there still read as
    unreachable."""
    files = {f.name for f in _mod()._shell_and_md_files()}
    assert "repo_hygiene_gates.sh" in files
    assert "gatekeeper-land.sh" in files


def test_the_plugin_shell_venues_are_still_in_scope():
    """Widening must not drop what already worked."""
    paths = [str(f) for f in _mod()._shell_and_md_files()]
    assert any("plugins/vibe-ic" in p and p.endswith(".md") for p in paths)


def test_the_venue_list_has_no_duplicates():
    """`PLUGIN.rglob` and the repo-root walk can overlap in a nested checkout;
    a file counted twice would inflate every hit list."""
    files = [f.resolve() for f in _mod()._shell_and_md_files()]
    assert len(files) == len(set(files))


# ── ruler ───────────────────────────────────────────────────────────────────
def test_every_program_stem_is_identifier_shaped():
    """`audit` replaced `\\b<stem>\\b` with token membership, which is only
    equivalent for identifier-shaped stems. `audit` asserts this at runtime;
    this pins it so the equivalence is checked even when nobody runs the
    auditor."""
    R = _mod()
    bad = [p.stem for p in R._list_programs()
           if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", p.stem)]
    assert bad == [], bad


def test_the_glob_dispatch_regex_reads_a_real_dispatcher():
    """Derived from the source, never hard-coded — so a new dispatcher is
    picked up and a retired one stops counting."""
    R = _mod()
    disp = (R.PLUGIN / "programs" / "phase1_doc_one_shot_runner.py")
    pats = R._GLOB_DISPATCH_RE.findall(disp.read_text(errors="replace"))
    assert "*_protocol_synth.py" in pats, pats


def _glob_is_specific_enough(pat: str) -> bool:
    """The guard `audit` applies, restated once so the test asserts the RULE
    rather than re-deriving it inline."""
    return pat.count("*") == 1 and len(pat) > 5


def test_a_glob_too_loose_to_mean_anything_is_rejected():
    """`glob("*.py")` reaches every program, so honouring it would mark the
    whole tree reachable and make the audit vacuous — the exact defect this
    instrument exists to catch, committed by the instrument itself."""
    for pat in ("*.py", "*", "**/*.py", "a*.py"):
        assert not _glob_is_specific_enough(pat), pat


def test_a_real_family_glob_is_accepted():
    """The rejection above must not swallow the case the venue was added for —
    otherwise the 14 dispatched modules go back to being false orphans."""
    for pat in ("*_protocol_synth.py", "*_census.py", "*_one_shot_runner.py"):
        assert _glob_is_specific_enough(pat), pat


def test_the_guard_is_the_one_audit_applies():
    """Pinned against the source, so the two cannot drift apart: a rule
    restated in a test is a second copy of a value it cannot see."""
    R = _mod()
    import inspect
    src = inspect.getsource(R.audit)
    assert 'pat.count("*") == 1 and len(pat) > 5' in src, (
        "audit's glob guard changed shape; this test now asserts a rule the "
        "program no longer applies")


def test_the_import_regex_matches_both_import_shapes():
    """`_IMPORT_RE` replaced a per-program line-anchored scan; it must still
    see both forms and nothing else."""
    R = _mod()
    found = {n for m in R._IMPORT_RE.findall(
        "import foo_check\nfrom bar_check import x\n"
        "# import commented_out\nxs = 'baz_check'\n") for n in m if n}
    assert found == {"foo_check", "bar_check"}, found
