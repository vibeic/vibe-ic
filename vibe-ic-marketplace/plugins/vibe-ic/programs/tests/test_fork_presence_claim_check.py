#!/usr/bin/env python3
"""vibe-ic — a ledger that says a tool is not shipped, about tools that are.

`integrated = bool(ref)` where `ref` comes from parsing the Dockerfiles. A tool
whose pin the resolver cannot find is indistinguishable, in the output, from one
that genuinely is not shipped — and the label chosen for that state,
`not_layered — nothing to assess`, asserts the second.

Measured against `vibeic-eda:0.2.45` on 2026-07-30: five of the six tools in
that state are in the image, including `ciel`, whose managed store both sign-off
PDKs symlink into. Each is excluded from every upstream assessment while
shipping to users (vibeic-eda#32).

This check does not redefine `integrated` — that flag gates the assessment for
every tool. It tests the CLAIM against the image.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import fork_presence_claim_check as C  # noqa: E402


def _ledger(tmp_path, **tools) -> str:
    """`tools` maps name → integrated(bool)."""
    d = tmp_path / "ledger"
    d.mkdir(exist_ok=True)
    for name, integrated in tools.items():
        (d / f"{name}.json").write_text(
            json.dumps({"tool": name, "integrated": integrated}))
    return str(d)


def _docker(present=(), *, missing_docker=False, no_completion=False):
    """Substitute the container probe; `present` are paths that exist."""
    def run(argv, timeout=180):
        if missing_docker:
            return 127, "", "docker not found"
        if no_completion:
            return 1, "", "container exploded"
        script = argv[-1]
        lines = []
        for chunk in script.split(";"):
            chunk = chunk.strip()
            if not chunk.startswith('[ -e "'):
                continue
            path = chunk.split('"')[1]
            if path in present:
                tool = chunk.split('echo "FOUND ')[1].split()[0]
                lines.append(f"FOUND {tool} {path}")
        return 0, "\n".join(lines + ["PROBE_DONE"]) + "\n", ""
    return run


def test_a_shipped_tool_claimed_absent_is_caught(monkeypatch, tmp_path, capsys):
    """THE defect: OpenSTA's shape."""
    monkeypatch.setattr(C, "_run", _docker(present=("/foss/tools/bin/sta",)))
    rc = C.main(["--ledger", _ledger(tmp_path, OpenSTA=False)])
    err = capsys.readouterr().err
    assert rc == C.RC_CONTRADICTED
    assert "OpenSTA" in err and "/foss/tools/bin/sta" in err


def test_a_genuinely_absent_tool_passes(monkeypatch, tmp_path):
    """…or the test above is met by a check that always fails.
    OpenROAD-flow-scripts really is not in the image."""
    monkeypatch.setattr(C, "_run", _docker(present=()))
    assert C.main(["--ledger",
                   _ledger(tmp_path, **{"OpenROAD-flow-scripts": False})]) == C.RC_OK


def test_an_integrated_tool_is_not_probed(monkeypatch, tmp_path):
    """The check is about ABSENCE CLAIMS. A tool the ledger says IS shipped
    makes no claim to contradict, and probing it would invent a finding."""
    monkeypatch.setattr(C, "_run", _docker(present=("/foss/tools/bin/sta",)))
    assert C.main(["--ledger", _ledger(tmp_path, OpenSTA=True)]) == C.RC_OK


def test_no_docker_is_not_a_confirmed_absence(monkeypatch, tmp_path):
    """An absence that could not be tested has not been confirmed."""
    monkeypatch.setattr(C, "_run", _docker(missing_docker=True))
    assert C.main(["--ledger", _ledger(tmp_path, OpenSTA=False)]) \
        == C.RC_CANNOT_CHECK


def test_a_probe_that_did_not_finish_is_not_absence(monkeypatch, tmp_path,
                                                    capsys):
    """A container that died prints nothing, which looks exactly like "no paths
    found" — the shape this whole check exists to reject, pointed at itself."""
    monkeypatch.setattr(C, "_run", _docker(no_completion=True))
    rc = C.main(["--ledger", _ledger(tmp_path, OpenSTA=False)])
    assert rc == C.RC_CANNOT_CHECK, \
        f"a dead probe was read as a confirmed absence (rc={rc})"
    assert "did not complete" in capsys.readouterr().err


def test_a_tool_with_no_known_path_is_unknown_not_absent(monkeypatch, tmp_path,
                                                         capsys):
    """Nowhere to look is not looked-and-gone. Reporting it as verified absent
    would launder a gap in the registry into a positive finding."""
    monkeypatch.setattr(C, "_run", _docker(present=()))
    rc = C.main(["--ledger", _ledger(tmp_path, some_new_tool=False)])
    err = capsys.readouterr().err
    assert rc == C.RC_OK
    assert "no known path" in err and "some_new_tool" in err


def test_an_unreadable_ledger_blocks_the_verdict(monkeypatch, tmp_path):
    """A ledger that cannot be parsed makes no claim, and a missing claim must
    not be counted as a claim that held."""
    d = tmp_path / "ledger"
    d.mkdir()
    (d / "broken.json").write_text("{not json")
    monkeypatch.setattr(C, "_run", _docker(present=()))
    assert C.main(["--ledger", str(d)]) == C.RC_CANNOT_CHECK


def test_a_missing_ledger_directory_cannot_be_checked(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "_run", _docker(present=()))
    assert C.main(["--ledger", str(tmp_path / "absent")]) == C.RC_CANNOT_CHECK


def test_every_tool_integrated_is_a_clean_state(monkeypatch, tmp_path, capsys):
    """No absence claims at all is genuinely clean, not an empty scan: there is
    nothing for this check to contradict."""
    monkeypatch.setattr(C, "_run", _docker(present=()))
    assert C.main(["--ledger", _ledger(tmp_path, OpenSTA=True, ciel=True)]) \
        == C.RC_OK


def test_the_json_report_names_what_was_found(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "_run",
                        _docker(present=("/usr/local/bin/ciel",)))
    out = tmp_path / "rep.json"
    C.main(["--ledger", _ledger(tmp_path, ciel=False), "--json", str(out)])
    rep = json.loads(out.read_text())
    assert rep["program"] == "fork_presence_claim_check"
    assert rep["contradicted"] == {"ciel": "/usr/local/bin/ciel"}


# --------------------------------------------------------------------------
# the known-debt register — it must not amnesty the future
# --------------------------------------------------------------------------

def _reg(tmp_path, **contradicted):
    p = tmp_path / "reg.json"
    p.write_text(json.dumps({"contradicted": contradicted}))
    return str(p)


def test_a_recorded_contradiction_does_not_block_a_landing(monkeypatch,
                                                           tmp_path, capsys):
    """The five need `integrated` redefined, which is not a checker's call. A
    gate that fails every commit until then is a gate someone deletes."""
    monkeypatch.setattr(C, "_run", _docker(present=("/foss/tools/bin/sta",)))
    rc = C.main(["--ledger", _ledger(tmp_path, OpenSTA=False),
                 "--baseline", _reg(tmp_path, OpenSTA="/foss/tools/bin/sta")])
    err = capsys.readouterr().err
    assert rc == C.RC_OK
    assert "recorded as known debt" in err, \
        "the debt was subtracted silently — an unseen debt becomes permission"


def test_a_NEW_contradiction_still_fails(monkeypatch, tmp_path):
    """The whole point: one recorded, a second appears, and the second must
    stop the landing."""
    monkeypatch.setattr(C, "_run", _docker(
        present=("/foss/tools/bin/sta", "/usr/local/bin/ciel")))
    rc = C.main(["--ledger", _ledger(tmp_path, OpenSTA=False, ciel=False),
                 "--baseline", _reg(tmp_path, OpenSTA="/foss/tools/bin/sta")])
    assert rc == C.RC_CONTRADICTED


def test_an_unreadable_register_is_not_an_empty_one(monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setattr(C, "_run", _docker(present=("/foss/tools/bin/sta",)))
    assert C.main(["--ledger", _ledger(tmp_path, OpenSTA=False),
                   "--baseline", str(bad)]) == C.RC_CANNOT_CHECK


def test_a_missing_register_file_still_fails_on_a_contradiction(monkeypatch,
                                                                tmp_path):
    """Absent register = nothing recorded, which must FAIL rather than pass for
    lack of a file."""
    monkeypatch.setattr(C, "_run", _docker(present=("/foss/tools/bin/sta",)))
    assert C.main(["--ledger", _ledger(tmp_path, OpenSTA=False),
                   "--baseline", str(tmp_path / "nope.json")]) \
        == C.RC_CONTRADICTED


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
