#!/usr/bin/env python3
"""vibe-ic — a CI declaration whose argv the gate's own parser rejects.

Every test here is about the DISCRIMINATOR, because "it fires" was never the
hard part. Eight of the CI umbrella's declarations use
`run_tolerating_uncheckable`, where rc 2 legitimately means "I could not look",
and a rule that read every rc 2 as a bad invocation would fail all of them on a
machine without the tools — which is how a gate earns being switched off rather
than fixed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _argv_parse_smoke as S                       # noqa: E402
import gate_declared_argv_parses_check as C         # noqa: E402
import gate_discloses_denominator_check as G        # noqa: E402


def _repo(tmp_path: Path, declarations: str) -> Path:
    """A throwaway tree carrying only a CI umbrella."""
    script = tmp_path / "tools" / "ci" / "repo_hygiene_gates.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/usr/bin/env bash\n" + declarations, encoding="utf-8")
    return tmp_path


def _gate(tmp_path: Path, name: str, body: str) -> str:
    (tmp_path / name).write_text("#!/usr/bin/env python3\n" + body,
                                 encoding="utf-8")
    return name


#: A gate with one required flag. Declared WITH it, it parses; declared with a
#: renamed one, argparse rejects the command line before the gate's first
#: statement runs.
_NEEDS_FLAG = ("import argparse, sys\n"
               "p = argparse.ArgumentParser()\n"
               "p.add_argument('--needed', required=True)\n"
               "p.parse_args()\n"
               "print('checked 3 things'); sys.exit(0)\n")


# ---------------------------------------------------------------------------
# the finding
# ---------------------------------------------------------------------------

def test_a_stale_flag_in_a_declaration_is_a_finding(tmp_path):
    """THE defect. The declaration and the program are edited independently;
    nothing today compares them."""
    _gate(tmp_path, "toy_gate.py", _NEEDS_FLAG)
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/toy_gate.py" '
                           '--renamed x\n')
    res = C.audit(root)
    assert len(res["rejected"]) == 1, res
    assert res["accepted"] == 0
    assert "toy" == res["rejected"][0]["gate"]


def test_the_verdict_is_rc_1(tmp_path, capsys):
    _gate(tmp_path, "toy_gate.py", _NEEDS_FLAG)
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/toy_gate.py" '
                           '--renamed x\n')
    assert C.main(["--repo-root", str(root)]) == C.RC_FAIL
    assert "cannot be validly invoked" in capsys.readouterr().err


def test_a_declaration_naming_a_program_that_is_gone_is_a_finding(tmp_path):
    """A deleted gate still declared is the same defect one step earlier, and
    counting it as a coverage gap would let it read as benign."""
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/never_made.py"\n')
    res = C.audit(root)
    assert len(res["rejected"]) == 1
    assert "does not exist" in res["rejected"][0]["detail"]


def test_an_extra_argument_is_rejected(tmp_path):
    """`parse_args` does the leftover-argument check AFTER `parse_known_args`
    returns. A smoke that stopped at the inner call would skip exactly the
    check that catches a declaration carrying a flag the gate dropped."""
    _gate(tmp_path, "toy_gate.py",
          "import argparse\n"
          "p = argparse.ArgumentParser()\n"
          "p.add_argument('--a')\n"
          "p.parse_args()\n")
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/toy_gate.py" '
                           '--a 1 --b 2\n')
    assert len(C.audit(root)["rejected"]) == 1


# ---------------------------------------------------------------------------
# the reverse case — what must STILL pass
# ---------------------------------------------------------------------------

def test_a_gate_that_parses_then_refuses_its_input_is_not_a_finding(tmp_path):
    """THE discriminator. `run_tolerating_uncheckable` gates exit 2 to say
    "I could not look" — the state `_gate_dispatch.sh` is built around. Reading
    that as a bad invocation would fail eight real declarations for behaving
    exactly as designed."""
    _gate(tmp_path, "toy_gate.py",
          "import argparse, sys\n"
          "p = argparse.ArgumentParser()\n"
          "p.add_argument('--check', action='store_true')\n"
          "p.parse_args()\n"
          "print('VACUOUS_PASS: no corpus to examine', file=sys.stderr)\n"
          "sys.exit(2)\n")
    root = _repo(tmp_path, 'run_tolerating_uncheckable "toy" "$ROOT" python3 '
                           '"$ROOT/toy_gate.py" --check\n')
    res = C.audit(root)
    assert res["rejected"] == [], res
    assert res["accepted"] == 1
    assert C.main(["--repo-root", str(root)]) == C.RC_OK


def test_a_valid_declaration_passes(tmp_path):
    _gate(tmp_path, "toy_gate.py", _NEEDS_FLAG)
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/toy_gate.py" '
                           '--needed x\n')
    res = C.audit(root)
    assert res["rejected"] == [] and res["accepted"] == 1


def test_the_shipped_ci_umbrella_is_clean():
    """The corpus. A rule that fires on legitimate existing state is a false
    positive however good its motivation, so the shipped declarations are the
    standing control."""
    root = PROGRAMS.parents[3]
    res = C.audit(root)
    assert "error" not in res, res
    assert res["rejected"] == [], res["rejected"]
    assert res["accepted"] == res["declared"] > 0, res


# ---------------------------------------------------------------------------
# what the smoke may NOT claim
# ---------------------------------------------------------------------------

def test_a_parse_of_some_other_argv_is_not_acceptance(tmp_path):
    """A program that builds a throwaway parser first would otherwise report
    ACCEPTED for an argv nothing ever looked at — a vacuous pass inside the one
    program whose job is to find them."""
    _gate(tmp_path, "toy_gate.py",
          "import argparse\n"
          "argparse.ArgumentParser().parse_args(['--x', '1'])\n"
          "p = argparse.ArgumentParser()\n"
          "p.add_argument('--needed', required=True)\n"
          "p.parse_args()\n")
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/toy_gate.py" '
                           '--renamed 1\n')
    assert len(C.audit(root)["rejected"]) == 1


def test_a_throwaway_empty_parse_cannot_stand_in_for_the_real_one(tmp_path):
    """35 of the 63 shipped declarations pass no arguments, and for those
    `parse_args([])` on a throwaway parser is byte-identical to the real parse.
    The re-probe with an unknown option is what makes the two distinguishable —
    without it, more than half the population could report ACCEPTED over an
    argv nothing examined."""
    _gate(tmp_path, "toy_gate.py",
          "import argparse\n"
          "argparse.ArgumentParser().parse_args([])\n"   # the decoy
          "p = argparse.ArgumentParser()\n"
          "p.add_argument('--needed', required=True)\n"  # the real one
          "p.parse_args()\n")
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/toy_gate.py"\n')
    res = C.audit(root)
    assert len(res["rejected"]) == 1, res
    assert "passes no arguments" in res["rejected"][0]["detail"]


def test_the_reprobe_does_not_invent_a_finding(tmp_path):
    """Its own reverse case. The re-probe appends a token the parser cannot
    know, so EVERY strict parser objects to it; reading that objection as a
    defect would fail every argument-less declaration in the script."""
    _gate(tmp_path, "toy_gate.py",
          "import argparse\n"
          "p = argparse.ArgumentParser()\n"
          "p.add_argument('--optional', default='x')\n"
          "p.parse_args()\n")
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/toy_gate.py"\n')
    res = C.audit(root)
    assert res["rejected"] == [] and res["accepted"] == 1


def test_a_gate_that_never_parses_is_reported_not_credited(tmp_path, capsys):
    """"I could not measure this" is its own answer. Folding it into ACCEPTED
    would be the coverage claim this file exists to refuse; failing on it would
    fire on every gate that reads `sys.argv` by hand."""
    _gate(tmp_path, "toy_gate.py", "import sys\nsys.exit(0)\n")
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/toy_gate.py"\n')
    res = C.audit(root)
    assert res["accepted"] == 0
    assert len(res["not_parser_driven"]) == 1
    assert C.main(["--repo-root", str(root)]) == C.RC_OK
    assert "NOT PARSER DRIVEN" in capsys.readouterr().err


def test_the_gate_body_never_runs(tmp_path):
    """The claim that makes this cheap enough to run at every landing, and the
    one `_gate_dispatch.sh`'s corpus-write guard would otherwise catch: the
    smoke stops at the parser, so no gate writes into the tree it audits."""
    _gate(tmp_path, "toy_gate.py",
          "import argparse, pathlib\n"
          "argparse.ArgumentParser().parse_args()\n"
          "pathlib.Path('SIDE_EFFECT').write_text('x')\n")
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/toy_gate.py"\n')
    assert C.audit(root)["accepted"] == 1
    assert not (tmp_path / "SIDE_EFFECT").exists()


def test_acceptance_needs_both_channels(tmp_path):
    """rc alone cannot carry the claim: a program that never parses is free to
    exit with any status, including this one."""
    _gate(tmp_path, "toy_gate.py",
          f"import sys\nsys.exit({S.RC_PARSER_ACCEPTED})\n")
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/toy_gate.py"\n')
    res = C.audit(root)
    assert res["accepted"] == 0
    assert len(res["not_parser_driven"]) == 1


# ---------------------------------------------------------------------------
# why this is a new program — measured, not asserted
# ---------------------------------------------------------------------------

def test_the_existing_declaration_auditor_does_not_catch_it(tmp_path):
    """`gate_discloses_denominator_check` parses these very declarations and
    drives them, and acts only on `returncode == 0`. The rejected declaration
    exits 2 and is dropped without a word — which is why the property needed an
    owner rather than a line in that file."""
    _gate(tmp_path, "toy_gate.py", _NEEDS_FLAG)
    root = _repo(tmp_path, 'run "toy" "$ROOT" python3 "$ROOT/toy_gate.py" '
                           '--renamed x\n')
    verdict, findings = G.audit(root)
    assert verdict == "PASS" and findings == []
    assert len(C.audit(root)["rejected"]) == 1


# ---------------------------------------------------------------------------
# never a vacuous pass about itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body", ["", "# no declarations here\n"])
def test_an_empty_population_is_not_a_pass(tmp_path, body, capsys):
    root = _repo(tmp_path, body)
    assert C.main(["--repo-root", str(root)]) == C.RC_NOT_MEASURED
    assert "NOT MEASURED" in capsys.readouterr().err


def test_a_missing_script_is_not_a_pass(tmp_path, capsys):
    assert C.main(["--repo-root", str(tmp_path)]) == C.RC_NOT_MEASURED
    assert "NOT MEASURED" in capsys.readouterr().err
