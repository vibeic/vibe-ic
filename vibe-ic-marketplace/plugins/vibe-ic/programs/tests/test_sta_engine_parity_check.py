#!/usr/bin/env python3
"""vibe-ic — two timing engines in one image, disagreeing silently.

Measured 2026-07-30 in `vibeic-eda:0.2.45`: `openroad`'s built-in STA had 10 of
10 vibeic superset commands, the standalone `sta` had 0. The built-in engine is
our `sta-timing-eco` code; the standalone binary is upstream's, byte-identical
to the base image's and never copied out of the build (vibeic-eda#8).

Nothing errors when they diverge. A flow step that shells out to `sta` gets an
engine without crosstalk delta-delay or path-based analysis, and an absent Tcl
command in a script that does not call it is indistinguishable from a working
install.

The version strings do not help and actively mislead: `openroad` reports 2.7.0
from a hardcoded bazel genrule while carrying current code, `sta` reports 3.1.0
from a June build with none of it. So the check has to be the COMMAND SURFACE.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import sta_engine_parity_check as P  # noqa: E402


def _fake_run(openroad_has, sta_has, *, rc=0, docker_missing=False):
    """Substitute the docker call; `*_has` are the commands each engine reports."""
    def run(argv, timeout=180):
        if docker_missing:
            return 127, "", "docker not found"
        entry = argv[argv.index("--entrypoint") + 1]
        have = openroad_has if entry == "openroad" else sta_has
        if have is None:                      # the silent-no-output case
            return rc, "", "container said nothing"
        lines = [f"{'HAVE' if c in have else 'MISS'} {c}"
                 for c in P.SUPERSET_COMMANDS]
        return rc, "\n".join(lines) + "\n", ""
    return run


ALL = set(P.SUPERSET_COMMANDS)


def test_the_real_divergence_is_caught(monkeypatch):
    """THE defect: everything in openroad, nothing in sta."""
    monkeypatch.setattr(P, "_run", _fake_run(ALL, set()))
    assert P.main([]) == P.RC_DISAGREE


def test_agreement_passes(monkeypatch):
    """…or the test above is met by a gate that always fails."""
    monkeypatch.setattr(P, "_run", _fake_run(ALL, ALL))
    assert P.main([]) == P.RC_AGREE


def test_divergence_the_other_way_is_also_caught(monkeypatch):
    """A command in `sta` but not `openroad` is the same class of fault, and a
    check that only looks one way would miss a build that ships the superset
    standalone while the built-in engine goes stale."""
    monkeypatch.setattr(P, "_run", _fake_run(set(), ALL))
    assert P.main([]) == P.RC_DISAGREE


def test_a_command_in_neither_is_a_stale_list_not_a_finding(monkeypatch, capsys):
    """If the fork renames a command, every probe misses it in BOTH engines.
    Calling that a packaging fault would make the gate cry wolf until someone
    switches it off; it is reported as list drift instead."""
    both = ALL - {"whatif_eco"}
    monkeypatch.setattr(P, "_run", _fake_run(both, both))
    rc = P.main([])
    err = capsys.readouterr().err
    assert rc == P.RC_AGREE, "list drift was reported as a divergence"
    assert "stale" in err and "whatif_eco" in err, \
        "the drifted entry was silently dropped from the denominator"


def test_no_docker_is_not_agreement(monkeypatch):
    """A parity check that could not run has not found parity."""
    monkeypatch.setattr(P, "_run", _fake_run(ALL, ALL, docker_missing=True))
    assert P.main([]) == P.RC_CANNOT_CHECK


def test_a_silent_engine_is_not_an_empty_engine(monkeypatch, capsys):
    """The failure I actually hit: `sta` takes its script positionally and
    `openroad` after -exit, so the wrong argv form produces NO output at all.
    Read as "no commands present" that manufactures a divergence out of a
    calling-convention mistake."""
    monkeypatch.setattr(P, "_run", _fake_run(ALL, None))
    rc = P.main([])
    assert rc == P.RC_CANNOT_CHECK, \
        f"a silent engine was read as an empty one (rc={rc})"
    assert "no probe output" in capsys.readouterr().err


def test_an_empty_probe_list_cannot_report_parity(monkeypatch):
    """Zero commands checked yields zero disagreements — the shape this gate
    exists to reject, pointed at itself."""
    monkeypatch.setattr(P, "_run", _fake_run(ALL, ALL))
    assert "error" in P.check("img", ())


def test_the_report_names_the_missing_commands(monkeypatch, capsys):
    """"They disagree" without saying how costs the reader a manual probe."""
    monkeypatch.setattr(P, "_run", _fake_run(ALL, ALL - {"report_pba"}))
    P.main([])
    err = capsys.readouterr().err
    assert "report_pba" in err
    assert "NOT in sta" in err


def test_the_json_report_is_machine_readable(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "_run", _fake_run(ALL, set()))
    out = tmp_path / "rep.json"
    P.main(["--json", str(out)])
    rep = json.loads(out.read_text())
    assert rep["program"] == "sta_engine_parity_check"
    assert rep["openroad_present"] == 10 and rep["sta_present"] == 0
    assert len(rep["only_openroad"]) == 10


# --------------------------------------------------------------------------
# the known-debt register — it must not become a blanket amnesty
# --------------------------------------------------------------------------

def _baseline(tmp_path, only_openroad=(), only_sta=()):
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"only_openroad": list(only_openroad),
                             "only_sta": list(only_sta)}))
    return str(p)


def test_a_recorded_divergence_does_not_block_a_landing(monkeypatch, tmp_path,
                                                        capsys):
    """vibeic-eda#8 cannot be fixed without an image rebuild. A gate that fails
    every commit until then is a gate someone deletes."""
    monkeypatch.setattr(P, "_run", _fake_run(ALL, set()))
    rc = P.main(["--baseline", _baseline(tmp_path, only_openroad=ALL)])
    err = capsys.readouterr().err
    assert rc == P.RC_AGREE
    assert "recorded as known debt" in err, \
        "the debt was subtracted silently — an unseen debt becomes permission"


def test_a_NEW_divergence_still_fails(monkeypatch, tmp_path):
    """The whole point. Nine recorded, a tenth appears: that tenth must stop the
    landing, or the register has amnestied the future as well as the past."""
    monkeypatch.setattr(P, "_run", _fake_run(ALL, set()))
    known = ALL - {"report_pba"}
    assert P.main(["--baseline", _baseline(tmp_path, only_openroad=known)]) \
        == P.RC_DISAGREE


def test_an_unreadable_baseline_is_not_an_empty_one(monkeypatch, tmp_path):
    """A corrupt register would otherwise read as "nothing is known", turning a
    recorded debt back into a hard failure — or worse, if inverted, turning an
    unknown into an amnesty. Neither guess is safe."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setattr(P, "_run", _fake_run(ALL, set()))
    assert P.main(["--baseline", str(bad)]) == P.RC_CANNOT_CHECK


def test_a_missing_baseline_file_behaves_as_no_recorded_debt(monkeypatch,
                                                             tmp_path):
    """Absent register = nothing recorded yet, which must FAIL on a real
    divergence rather than pass for lack of a file."""
    monkeypatch.setattr(P, "_run", _fake_run(ALL, set()))
    assert P.main(["--baseline", str(tmp_path / "absent.json")]) \
        == P.RC_DISAGREE


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
