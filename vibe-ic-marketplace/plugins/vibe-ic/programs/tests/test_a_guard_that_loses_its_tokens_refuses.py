"""A guard that cannot resolve its NDA tokens must REFUSE, never report clean.

The NDA literals moved out of the shipped plugin into the private config, so
"the token store is empty" stopped being a should-never-happen and became the
ORDINARY state of every public checkout and every CI job that has not been
handed the tokens. Two of the guards were not ready for it. MEASURED 2026-08-29,
with a token planted in the subject and the store emptied:

  source_chip_agnostic_check.py
      PASS (1 file(s) scanned): no forbidden chip / vendor / SKU tokens ...
      rc 0 — over a file that contained the token. `_build_nda_re()` returned
      the never-matching pattern `(?!x)x` under the comment "should never
      happen". A vacuous PASS: confident, specific, and false.

  nda_diff_scan_check.py
      Traceback ... _commercial_pdk.NoNdaLiterals
      rc 1 — the `except RuntimeError -> return 2` guards the diff ACQUISITION,
      and the token store is not consulted until `scan_unified_diff`, one
      statement outside that block. rc 1 on this gate is a MEASURED REFUSE, so
      the push preflight recorded verdict=REFUSE with a Python traceback as the
      finding's summary. A failed question wearing a finding's clothes.

BIDIRECTIONAL. The `configured` arm is not decoration: without it, both
assertions below are satisfied by a guard that refuses unconditionally, which
would disable the detectors entirely — a worse defect than the one being fixed.

chip-AGNOSTIC: about the shape of a detector, not about any design.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

from _nda_fixture_tokens import FICTIONAL_NDA_TOKENS  # noqa: E402

_BRAND = FICTIONAL_NDA_TOKENS["foundry_brand1"]
_SKU = FICTIONAL_NDA_TOKENS["sku_full"]


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    """A repository whose newest commit ADDS a token to a file AND to its
    message — the exact subject all four guards are supposed to catch."""
    repo = tmp_path_factory.mktemp("planted")
    prog = repo / "vibe-ic-marketplace/plugins/vibe-ic/programs"
    prog.mkdir(parents=True)
    (prog / "thing.py").write_text("VALUE = 1\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    (prog / "thing.py").write_text(f'VALUE = 1\nVENDOR = "{_BRAND}"\nPDK = "{_SKU}"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"wire up {_SKU} for the {_BRAND} flow")
    return repo


def _run(gate, args, *, tokens):
    env = {k: v for k, v in os.environ.items() if k != "VIBEIC_NDA_TOKENS"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if tokens:
        env["VIBEIC_NDA_TOKENS"] = json.dumps(FICTIONAL_NDA_TOKENS)
    proc = subprocess.run([sys.executable, "-B", str(_PROGRAMS / gate), *args],
                          capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def _argv(gate, planted):
    if gate == "source_chip_agnostic_check.py":
        return [str(planted / "vibe-ic-marketplace/plugins/vibe-ic")]
    if gate == "nda_tracked_tree_scan.py":
        return ["--repo", str(planted)]
    return ["--repo", str(planted), "--rev-range", "HEAD~1..HEAD"]


_GATES = ("commit_msg_nda_check.py", "nda_diff_scan_check.py",
          "source_chip_agnostic_check.py", "nda_tracked_tree_scan.py")


@pytest.mark.parametrize("gate", _GATES)
def test_without_tokens_the_guard_refuses_and_never_says_pass(gate, planted):
    rc, out, err = _run(gate, _argv(gate, planted), tokens=False)
    assert rc == 2, (
        f"{gate} exited {rc} with no token store. 0 is a clean bill of health "
        f"it cannot have earned; 1 is a MEASURED FINDING the push preflight "
        f"reads as REFUSE. 'I have nothing to match with' is rc 2 — the same "
        f"no-verdict channel as NOTHING_SCANNED.\n{out}\n{err}")
    assert "PASS" not in out.upper(), (
        f"{gate} printed a PASS while unable to look:\n{out}")
    assert "Traceback" not in err, (
        f"{gate} died instead of reporting. A guard's inability to answer is a "
        f"result it must render, not an exception it leaks:\n{err}")


@pytest.mark.parametrize("gate", _GATES)
def test_with_tokens_the_same_guard_still_catches_the_plant(gate, planted):
    """THE CONTROL ARM. Without it the refusals above are satisfied by a guard
    that refuses always, i.e. by turning the detector off."""
    rc, out, err = _run(gate, _argv(gate, planted), tokens=True)
    assert rc == 1, (
        f"{gate} exited {rc} on a subject that plants both a brand token and a "
        f"SKU token in an added line, an added file and the commit message. "
        f"The refusal test above is only meaningful if this arm still "
        f"FINDS.\n{out}\n{err}")


def test_no_guard_echoes_the_literal_it_matched(planted):
    """Masked reporting survives the move: a finding names the ROLE, never the
    token. A guard that leaks the token while reporting the leak is the whole
    failure it exists to prevent."""
    for gate in _GATES:
        rc, out, err = _run(gate, _argv(gate, planted), tokens=True)
        blob = out + err
        assert _BRAND not in blob, f"{gate} echoed the brand literal:\n{blob}"
        assert _SKU not in blob, f"{gate} echoed the SKU literal:\n{blob}"
