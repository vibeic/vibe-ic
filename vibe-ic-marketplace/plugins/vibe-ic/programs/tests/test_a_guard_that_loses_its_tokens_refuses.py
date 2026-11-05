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
from backlog_sanitize_check import (  # noqa: E402
    _shipped_plugin_version)

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
    # The two PROSE guards do not take a repo — they take the document they
    # audit. Plant the same SKU in one of each so the whole population below
    # runs against ONE fixture and one plant.
    notes = repo / "notes"
    notes.mkdir()
    (notes / "PRACTICAL_NOTES.md").write_text(
        f"# Notes\n\nThe flow was closed on the {_SKU} process.\n")
    (repo / "backlog.yaml").write_text(
        "type: enhancement\n"
        'component: "flow:pnr"\n'
        "title: routing note\n"
        f"pattern: the detailed router left a residual on the {_SKU} process.\n"
        # The shipped version, read the way the gate reads it: any other
        # value raises a SECOND finding, and an rc-1 control that would
        # be rc 1 anyway is not a control.
        f"plugin_version: {_shipped_plugin_version()}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"wire up {_SKU} for the {_BRAND} flow")
    return repo


@pytest.fixture(scope="module")
def _no_store(tmp_path_factory):
    """A private config that resolves to NO tokens.

    THE ENV VAR IS NOT THE ONLY TOKEN SOURCE. `_commercial_pdk` reads
    `VIBEIC_NDA_TOKENS` **or** the private config, and the config's default
    location is `~/.config/vibeic/commercial_pdk.json`. Dropping only the env
    var therefore built a "no token store" arm that is a no-token arm ONLY on a
    host that has no config — and the hosts that matter, the ones that actually
    run these guards for real, are precisely the configured ones.

    MEASURED 2026-08-30 on clean origin/main (v1.12.82), with a real private
    config present: all FOUR of the then-parametrized gates failed this arm,
    because every one of them could still answer. The arm was not asserting what
    it said; it was asserting that the host was unconfigured.

    `_load_private_config` returns the FIRST candidate that parses to a dict, and
    `VIBEIC_PRIVATE_CONFIG` is ahead of the home path in that list, so pointing it
    at `{}` short-circuits the home file without touching it."""
    cfg = tmp_path_factory.mktemp("nostore") / "commercial_pdk.json"
    cfg.write_text("{}\n")
    return cfg


def _run(gate, args, *, tokens, no_store=None):
    env = {k: v for k, v in os.environ.items() if k != "VIBEIC_NDA_TOKENS"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if tokens:
        env["VIBEIC_NDA_TOKENS"] = json.dumps(FICTIONAL_NDA_TOKENS)
    elif no_store is not None:
        env["VIBEIC_PRIVATE_CONFIG"] = str(no_store)
    proc = subprocess.run([sys.executable, "-B", str(_PROGRAMS / gate), *args],
                          capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def _argv(gate, planted):
    if gate == "source_chip_agnostic_check.py":
        return [str(planted / "vibe-ic-marketplace/plugins/vibe-ic")]
    if gate == "nda_tracked_tree_scan.py":
        return ["--repo", str(planted)]
    if gate == "practical_notes_specificity_check.py":
        return ["--paths", str(planted / "notes")]
    if gate == "backlog_sanitize_check.py":
        return ["--file", str(planted / "backlog.yaml")]
    return ["--repo", str(planted), "--rev-range", "HEAD~1..HEAD"]


# THE POPULATION IS THE RESOLVER'S OWN CALLER LIST, NOT THE FOUR THAT WERE
# MEASURED. `_commercial_pdk`'s module docstring names the guards that "must
# RECOGNISE the NDA foundry tokens"; the 2026-08-29 pass measured two of them,
# fixed two, and parametrized this test over four. The two PROSE guards below
# were named in that same list and were never driven — and they call the
# resolver inside a module-level rule table, so on a host with no token store
# they did not mis-report, they died at IMPORT: `--help` itself exited 1, and
# the Phase-2 P0 structural umbrella records rc 1 as a gate FAIL.
#
# MEASURED 2026-08-30 on gf180mcuD/spm through the one-shot runner: these two
# were the ONLY two of the umbrella's 246 structural checkers to FAIL, and they
# alone took `Overall: PASS_WITH_WAIVERS` to `Overall: FAIL`, Phase 2 to FAIL
# and Phase 3 to SKIPPED. The design never reached place-and-route because the
# host lacked OPTIONAL private config.
_GATES = ("commit_msg_nda_check.py", "nda_diff_scan_check.py",
          "source_chip_agnostic_check.py", "nda_tracked_tree_scan.py",
          "practical_notes_specificity_check.py", "backlog_sanitize_check.py")

# The echo test below runs over a STRICT SUBSET, and the exclusion is a
# disclosure, not a skip. MEASURED 2026-08-30 with the fixture SKU planted:
#   backlog_sanitize_check            emits `"matched": "<the literal>"`
#   practical_notes_specificity_check prints the offending source line verbatim
# Both therefore print the token while reporting that the token leaked — the
# masked-reporting contract the four converted guards meet through
# `_commercial_pdk.nda_mask_neighbourhood`. That is a SECOND defect in the same
# two files and it is deliberately NOT fixed here: this change is the import
# crash alone, and widening it would mean the crash fix could not be reverted
# on its own. Adding these two to `_ECHO_GATES` is the follow-up's job.
_ECHO_GATES = ("commit_msg_nda_check.py", "nda_diff_scan_check.py",
               "source_chip_agnostic_check.py", "nda_tracked_tree_scan.py")


@pytest.mark.parametrize("gate", _GATES)
def test_without_tokens_the_guard_refuses_and_never_says_pass(gate, planted,
                                                              _no_store):
    rc, out, err = _run(gate, _argv(gate, planted), tokens=False,
                        no_store=_no_store)
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
    for gate in _ECHO_GATES:
        rc, out, err = _run(gate, _argv(gate, planted), tokens=True)
        blob = out + err
        assert _BRAND not in blob, f"{gate} echoed the brand literal:\n{blob}"
        assert _SKU not in blob, f"{gate} echoed the SKU literal:\n{blob}"


# ── the suite's OWN channel: a name with nothing in it is not a store ───────
#
# The two refusals above are correct and load-bearing, and they are also the
# reason the suite must be able to tell "this host has no tokens" from "this
# harness exported an empty variable". `programs/tests/conftest.py` supplies a
# FICTIONAL store through the same channel a configured host uses, so that the
# guards are MEASURED rather than refusing everywhere; it used `setdefault`,
# which keeps `VIBEIC_NDA_TOKENS=` — the shape `docker run -e VIBEIC_NDA_TOKENS=`
# produces — and that value resolves to `{}` in `_commercial_pdk`.
#
# MEASURED on tree 5e850b3acee8 with that variable exported empty:
# `source_chip_agnostic_check` exits 2 NO_NDA_TOKENS and
# test_v1_0_68_issue707r2_shapeb_tb_inferred_order::test_chip_agnostic_guard
# goes red about the TREE. Accepting rc=2 there would blind the strictest guard
# in this repo; the fix belongs at the channel.

_CONFTEST_PROBE = (
    "import json, os, sys;"
    "sys.path.insert(0, %r);"
    "import conftest;"
    "sys.stdout.write(os.environ.get('VIBEIC_NDA_TOKENS', '<unset>'))"
)


def _tokens_after_conftest(env_value):
    """What the suite's channel holds after conftest runs, prove-by-run."""
    env = dict(os.environ)
    env.pop("VIBEIC_NDA_TOKENS", None)
    if env_value is not None:
        env["VIBEIC_NDA_TOKENS"] = env_value
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    tests_dir = str(Path(__file__).resolve().parent)
    r = subprocess.run([sys.executable, "-c", _CONFTEST_PROBE % tests_dir],
                       capture_output=True, text=True, env=env, cwd=tests_dir)
    assert r.returncode == 0, r.stderr[-800:]
    return r.stdout


@pytest.mark.parametrize("absent", [
    None,                       # the variable is not set at all
    "",                         # `docker run -e VIBEIC_NDA_TOKENS=`
    "   ",                      # blank
    "not json",                 # unparseable
    "{}",                       # an object with no tokens in it
    '{"foundry_brand1": "  "}',  # a role whose literal is blank
    '["a"]',                    # right JSON, wrong shape
])
def test_a_name_with_nothing_in_it_is_not_a_token_store(absent):
    """Every one of these is the ABSENCE of a store, so the suite supplies its
    fictional set — exactly as if the variable had never been set."""
    assert json.loads(_tokens_after_conftest(absent)) == FICTIONAL_NDA_TOKENS


def test_a_configured_host_keeps_its_own_store():
    """THE OTHER POLE, and the reason this is not a blanket overwrite: the
    suite must measure a genuinely configured host AS IT IS. Without this, the
    assertion above is satisfied by a conftest that clobbers real tokens."""
    real = json.dumps({"foundry_brand1": "zzq-not-a-real-brand",
                       "sku_full": "zzq-not-a-real-sku"})
    assert json.loads(_tokens_after_conftest(real)) == json.loads(real)
