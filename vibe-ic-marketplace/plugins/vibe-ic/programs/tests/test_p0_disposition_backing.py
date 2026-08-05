#!/usr/bin/env python3
"""vibe-ic — a P0 disposition may not promise a home the tree does not have.

The register that records why each un-invocable gate stays un-invocable can say
"driven from the FPGA-compile step" about a gate nothing drives, in the same
present tense it uses for a gate that IS driven. Measured at v1.9.79: 13 of the
36 pinned gates carry such a claim, and 3 carry one that is real.

Every test here is BIDIRECTIONAL by construction, because the two ways to break
this check are opposite:

  * too loose  -> a parked disposition ("NOT READY", "unwired") is read as a
                  broken promise, and the residual is noise;
  * too tight  -> the detector is narrowed until nothing matches, the residual
                  goes to zero, and the 13 real ones are swallowed.

`test_not_ready_is_not_a_home_claim` pins the first (it is an ACTUAL false
positive the first draft produced, on `phase1_gate_contract_check`).
`test_a_backed_claim_is_still_recognised_as_a_claim` pins the second: a
detector tightened to zero stops recognising the three genuine claims too, and
this test goes red before the residual can be quietly emptied.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import p0_disposition_backing_check as B  # noqa: E402

REPO_ROOT = PROGRAMS.parents[3]
PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"


# ---------------------------------------------------------------------------
# the claim detector — the two words that mean the opposite of each other
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "KEEP registered, driven at the final acceptance gate.",
    "KEEP registered, driven from the FPGA-compile step that emits the .qsf.",
    "KEEP registered, driven by the L-doc validators that supply the schema.",
    "KEEP registered, driven explicitly from the L-layer spec.",
    "READY — wired into tools/ci/repo_hygiene_gates.sh.",
])
def test_present_tense_home_claims_are_recognised(text):
    assert B.claims_a_home(text) is True


@pytest.mark.parametrize("text", [
    "NOT READY. Wiring it at the current scope buys a green over 7 of 29.",
    "KEEP registered, unwired. This is a schema question first.",
    "DISCLOSURE ONLY — plumbing deliberately not connected.",
    "",
])
def test_parked_dispositions_are_not_home_claims(text):
    assert B.claims_a_home(text) is False


def test_not_ready_is_not_a_home_claim():
    """The exact false positive the first draft of the checker produced.

    `phase1_gate_contract_check`'s disposition opens "NOT READY." and the naive
    `\\bREADY\\b` matched inside it, reporting a deliberately-parked gate as a
    broken promise. Reading a refusal as an assertion inverts the register.
    """
    parked = "NOT READY. Wiring it at the current scope buys a green over 7 of 29."
    assert "READY" in parked                      # the trap is really there
    assert B.claims_a_home(parked) is False       # and it is not taken


# ---------------------------------------------------------------------------
# the driver predicate — a mention is not an invocation
# ---------------------------------------------------------------------------

def test_a_comment_mention_is_not_an_invocation():
    """WRONG WAY 1: `tools/ci/repo_hygiene_gates.sh` contains the line
    "A third, `phase1_gate_contract_check`, is deliberately NOT here."
    A bare-name search reads that as a driver and clears the gate."""
    comment = ("# A third, `phase1_gate_contract_check`, is deliberately "
               "NOT here. Its scope is too narrow.\n")
    assert "phase1_gate_contract_check" in comment          # bare name present
    assert B.is_invoked("phase1_gate_contract_check", [comment]) is False


def test_a_real_invocation_is_an_invocation():
    """The reverse of the case above — same gate name, invocation form."""
    line = 'run "hygiene" "$PLUGIN" python3 programs/some_gate_check.py\n'
    assert B.is_invoked("some_gate_check", [line]) is True


# ---------------------------------------------------------------------------
# end-to-end over a synthetic tree — FORWARD and REVERSE in one fixture
# ---------------------------------------------------------------------------

def _tree(tmp_path: Path, dispositions: dict, driver_body: str = "") -> Path:
    """A minimal repo shaped like the real one."""
    programs = tmp_path / PLUGIN_REL / "programs"
    programs.mkdir(parents=True)
    (tmp_path / PLUGIN_REL / "flow").mkdir(parents=True)
    (tmp_path / "tools" / "ci").mkdir(parents=True)
    (tmp_path / "tools" / "ci" / "hygiene.sh").write_text(driver_body or "#\n")
    body = ["_REGISTER = {"]
    for gate, text in dispositions.items():
        body.append(f'    "{gate}": {{"disposition": {text!r}}},')
    body.append("}")
    (programs / B.REGISTRY_MODULE).write_text("\n".join(body) + "\n")
    (programs / "p0_gate_invocability_drift_check.py").write_text(
        "KNOWN_NOT_INVOCABLE = (\n"
        + "".join(f'    "{g}",\n' for g in dispositions)
        + ")\n")
    return tmp_path


def test_a_claim_with_no_driver_is_reported_unbacked(tmp_path):
    """FORWARD: the defect this check exists to catch."""
    root = _tree(tmp_path, {
        "promised_gate_check": "KEEP registered, driven at the acceptance gate.",
    })
    unbacked, backed, no_claim = B.measure(
        root, ["promised_gate_check"],
        root / PLUGIN_REL / "programs" / B.REGISTRY_MODULE)
    assert unbacked == ["promised_gate_check"]
    assert backed == [] and no_claim == []


def test_a_backed_claim_is_still_recognised_as_a_claim(tmp_path):
    """REVERSE — the anti-tighten-to-zero control.

    Same disposition wording as the forward case; the ONLY difference is that a
    driver invokes it. It must land in `backed`, not vanish. A detector
    narrowed until the residual is zero fails here, because `backed` empties at
    the same moment `unbacked` does.
    """
    root = _tree(tmp_path, {
        "promised_gate_check": "KEEP registered, driven at the acceptance gate.",
    }, driver_body="python3 programs/promised_gate_check.py --project-dir .\n")
    unbacked, backed, no_claim = B.measure(
        root, ["promised_gate_check"],
        root / PLUGIN_REL / "programs" / B.REGISTRY_MODULE)
    assert backed == ["promised_gate_check"]
    assert unbacked == [] and no_claim == []


def test_a_parked_gate_is_neither_backed_nor_unbacked(tmp_path):
    """The third bucket must stay a bucket: parking is not a promise."""
    root = _tree(tmp_path, {
        "parked_gate_check": "KEEP registered, unwired. Settle the schema first.",
    })
    unbacked, backed, no_claim = B.measure(
        root, ["parked_gate_check"],
        root / PLUGIN_REL / "programs" / B.REGISTRY_MODULE)
    assert no_claim == ["parked_gate_check"]
    assert unbacked == [] and backed == []


# ---------------------------------------------------------------------------
# the ratchet — it must be able to FAIL
# ---------------------------------------------------------------------------

def _run(root: Path, out: Path):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "p0_disposition_backing_check.py"),
         "--repo-root", str(root), "--json", str(out)],
        capture_output=True, text=True, timeout=30)


def test_a_newly_unbacked_claim_fails(tmp_path, monkeypatch):
    """A 14th broken promise exits 1. Without this, the check cannot fail and
    clearing both other bars would be meaningless."""
    root = _tree(tmp_path, {
        "brand_new_gate_check": "KEEP registered, driven from the step that emits it.",
    })
    out = tmp_path / "r.json"
    proc = _run(root, out)
    assert proc.returncode == B.RC_DRIFT, proc.stdout + proc.stderr
    payload = json.loads(out.read_text())
    assert payload["newly_unbacked"] == ["brand_new_gate_check"]
    assert payload["summary"]["pass"] is False


def test_a_recorded_name_that_got_wired_still_exits_zero(tmp_path):
    """Fixing a gate must not fail the ratchet — subset, not equality."""
    root = _tree(tmp_path, {
        "warn_acceptance_policy_check":
            "KEEP registered, driven at the final acceptance gate.",
    }, driver_body="python3 programs/warn_acceptance_policy_check.py --project-dir .\n")
    out = tmp_path / "r.json"
    proc = _run(root, out)
    assert proc.returncode == B.RC_OK, proc.stdout + proc.stderr
    assert json.loads(out.read_text())["unbacked"] == []


def test_missing_registry_cannot_measure(tmp_path):
    """Degrade loudly: an unreadable tree is rc 2, never a green rc 0."""
    (tmp_path / PLUGIN_REL / "programs").mkdir(parents=True)
    proc = _run(tmp_path, tmp_path / "r.json")
    assert proc.returncode == B.RC_CANNOT_MEASURE


# ---------------------------------------------------------------------------
# the live tree — the corpus arm
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (REPO_ROOT / "tools" / "ci").is_dir(),
                    reason="not running inside a full repo checkout")
def test_current_tree_holds_the_subset(tmp_path):
    out = tmp_path / "r.json"
    proc = _run(REPO_ROOT, out)
    assert proc.returncode == B.RC_OK, proc.stdout + proc.stderr
    payload = json.loads(out.read_text())
    assert payload["newly_unbacked"] == []
    # The three genuinely-backed claims are the live half of the reverse
    # control: they PROVE the detector still recognises a claim after every
    # tightening, so the residual cannot be emptied by narrowing.
    assert payload["backed"], "no claim recognised at all — detector collapsed"
    assert payload["summary"]["examined"] == (
        payload["summary"]["unbacked"] + payload["summary"]["backed"]
        + payload["summary"]["no_claim"])
