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
