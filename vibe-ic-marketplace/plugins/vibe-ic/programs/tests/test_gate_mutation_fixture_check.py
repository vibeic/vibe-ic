#!/usr/bin/env python3
"""Every dispatcher gate carries a fixture in BOTH directions — and the
requirement itself is shown to refuse.

The two acceptance scenarios this file exists for are the last two tests:
delete one gate's can-fail fixture and the meta-gate must refuse; add a gate
with no fixtures at all and it must refuse. A requirement that has only ever
been observed passing is the very thing this whole registry is about.

The fixtures themselves are EXECUTED here, one test per fixture, so a fixture
that stopped discriminating reddens by name rather than being counted as
present. Declaring a fixture and never driving it would rebuild the defect one
level up.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import gate_mutation_fixture_check as M                # noqa: E402
from gate_discloses_denominator_check import (         # noqa: E402
    parse_declarations)

_REPO = _PROGRAMS.parents[3]
_FIXTURES = _PROGRAMS / M.FIXTURES_DIRNAME


def _run(repo_root: Path, *extra: str):
    p = subprocess.run(
        [sys.executable, str(_PROGRAMS / "gate_mutation_fixture_check.py"),
         str(repo_root), *extra],
        capture_output=True, text=True, timeout=900)
    return p.returncode, p.stdout + p.stderr


def _slugs():
    return sorted(d.name for d in _FIXTURES.iterdir()
                  if d.is_dir() and (d / "fixture.json").is_file())


# ---------------------------------------------------------------- the shape

def test_the_repo_satisfies_the_requirement_today():
    rc, out = _run(_REPO)
    assert rc == 0, out


def test_every_declared_gate_is_either_fixtured_or_baselined():
    """No gate may be silently absent from both sides of the ledger."""
    result = M.audit(_REPO)
    assert result["declared"] > 0, result
    assert result["missing_both"] == [], result["missing_both"]
    assert result["incomplete"] == [], result["incomplete"]
    assert result["stale_baseline"] == [], result["stale_baseline"]
    assert result["baseline_should_shrink"] == [], (
        result["baseline_should_shrink"])
    assert result["orphan_fixtures"] == [], result["orphan_fixtures"]


def test_the_ledger_covers_the_declaration_list_exactly():
    """fixtures + baseline == the gates the dispatcher declares.

    Recomputed from `parse_declarations` rather than from the audit's own
    bookkeeping, so a bug that dropped a gate from BOTH sides cannot make
    both halves agree with each other.
    """
    declared = {d.label for d in parse_declarations(M.hygiene_script(_REPO))}
    fixtures, broken = M.load_fixtures(_PROGRAMS)
    assert broken == [], broken
    fixtured = {f.label for f in fixtures}
    baselined = set(M._load_baseline(_PROGRAMS))
    assert not (fixtured & baselined), fixtured & baselined
    assert fixtured | baselined == declared, {
        "unaccounted": sorted(declared - (fixtured | baselined)),
        "not_declared": sorted((fixtured | baselined) - declared),
    }


# ------------------------------------------------------- the fixtures RUN

@pytest.mark.parametrize("slug", _slugs())
def test_fixture_discriminates(slug):
    """The gate accepts can_pass and REJECTS the mutation, by the named message."""
    spec = json.loads((_FIXTURES / slug / "fixture.json").read_text(
        encoding="utf-8"))
    label = spec["gate_label"]
    decl = {d.label: d for d in parse_declarations(
        M.hygiene_script(_REPO))}.get(label)
    assert decl is not None, f"{slug} names a gate nothing declares: {label!r}"
    fx = M.Fixture(_FIXTURES / slug, spec)
    assert fx.structural_defects() == [], fx.structural_defects()
    findings = M.execute_fixture(fx, decl, _REPO)
    assert findings == [], "\n".join(findings)


def test_the_mutation_is_never_stored_on_disk():
    """No fixture may commit the tree its gate rejects.

    MEASURED, and it is why `can_fail/` does not exist as a concept here: a
    stored tree carrying the injected always-succeed line put
    `neutered_gate_tree_check` at `[FAIL] 1 finding(s) over 3819 module(s)`
    against the real plugin — the gate working correctly, over the fixture
    that was supposed to be proving it.
    """
    stored = [d.name for d in _FIXTURES.iterdir()
              if d.is_dir() and (d / "can_fail").exists()]
    assert stored == [], stored


# ------------------------------------------------------------- ACCEPTANCE

def _sandbox(tmp_path: Path) -> Path:
    """A throwaway repo carrying only what this gate reads."""
    root = tmp_path / "repo"
    (root / "tools" / "ci").mkdir(parents=True)
    shutil.copy(M.hygiene_script(_REPO),
                root / "tools" / "ci" / "repo_hygiene_gates.sh")
    dst = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    dst.mkdir(parents=True)
    shutil.copytree(_FIXTURES, dst / M.FIXTURES_DIRNAME)
    return root


def test_deleting_one_gates_can_fail_fixture_is_refused(tmp_path):
    """ACCEPT 1 — delete a can-fail fixture; the meta-gate must refuse."""
    root = _sandbox(tmp_path)
    fixtures = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" /
                "programs" / M.FIXTURES_DIRNAME)
    victim = fixtures / "no-gate-is-left-neutered"
    assert (victim / "mutate.py").is_file()

    rc, before = _run(root)
    assert rc == 0, before

    (victim / "mutate.py").unlink()
    rc, after = _run(root)
    assert rc == 1, after
    assert "no mutate.py" in after, after
    assert "the direction the gate must REJECT is undeclared" in after, after


def test_a_new_gate_with_no_fixtures_is_refused(tmp_path):
    """ACCEPT 2 — add a gate carrying no fixtures; the meta-gate must refuse."""
    root = _sandbox(tmp_path)
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"

    rc, before = _run(root)
    assert rc == 0, before

    label = "a brand new gate that nobody wrote a fixture for"
    script.write_text(
        script.read_text(encoding="utf-8")
        + f'\nrun "{label}" "$ROOT" python3 "$PG/some_new_check.py"\n',
        encoding="utf-8")
    rc, after = _run(root)
    assert rc == 1, after
    assert label in after, after
    assert "carries NEITHER a can-pass nor a can-fail fixture" in after, after


def test_a_baseline_entry_that_gained_a_fixture_must_shrink(tmp_path):
    """The baseline may only shrink: keeping an entry that has a fixture fails."""
    root = _sandbox(tmp_path)
    base = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs" /
            M.FIXTURES_DIRNAME / "baseline.json")
    doc = json.loads(base.read_text(encoding="utf-8"))
    spec = json.loads((_FIXTURES / "no-gate-is-left-neutered" /
                       "fixture.json").read_text(encoding="utf-8"))
    doc["gates_without_a_mutation_fixture"][spec["gate_label"]] = "re-added"
    base.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    rc, out = _run(root)
    assert rc == 1, out
    assert "the baseline may only shrink" in out, out


def test_a_baseline_entry_for_a_retired_gate_is_refused(tmp_path):
    """A baseline that outlives its gate hides the next gate that needs one."""
    root = _sandbox(tmp_path)
    base = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs" /
            M.FIXTURES_DIRNAME / "baseline.json")
    doc = json.loads(base.read_text(encoding="utf-8"))
    doc["gates_without_a_mutation_fixture"]["a gate that was retired"] = "gone"
    base.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    rc, out = _run(root)
    assert rc == 1, out
    assert "no longer declares" in out, out


def test_an_empty_message_pin_is_refused(tmp_path):
    """A rejection that names nothing cannot be told from a refusal to look."""
    root = _sandbox(tmp_path)
    spec = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs" /
            M.FIXTURES_DIRNAME / "no-gate-is-left-neutered" / "fixture.json")
    doc = json.loads(spec.read_text(encoding="utf-8"))
    doc["expect_fail_message"] = "  "
    spec.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    rc, out = _run(root)
    assert rc == 1, out
    assert "expect_fail_message is empty" in out, out


def test_a_tree_with_no_declarations_refuses_rather_than_passing(tmp_path):
    """rc 2, not rc 0: a requirement that enumerated nothing has not been met."""
    root = _sandbox(tmp_path)
    (root / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        "#!/usr/bin/env bash\necho nothing\n", encoding="utf-8")
    rc, out = _run(root)
    assert rc == 2, out
    assert "enumerated nothing" in out, out
