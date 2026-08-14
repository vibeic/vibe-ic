"""vibe-ic#1498 — the LANDING SCRIPT must publish the hygiene tier gate by gate.

`programs/tests/test_issue1498_hygiene_subgate_differential.py` proves what the
verdict does with per-gate lines. It builds its own log text, so it stays green
if `gatekeeper-land.sh` stops emitting them — and a differential that is correct
about input nothing produces is the shape this repo removes from gates one at a
time.

This file closes that. It EXTRACTS `run_hygiene_tier` from the real
`gatekeeper-land.sh` and EXECUTES it, against a throwaway repo whose hygiene
script is a stub that writes a chosen record. Reverting the wiring makes these
red; a text match for a reassuring word would not.

It lives under `tools/` on purpose — that is the tree `run_repo_tools_pytest`
(vibe-ic#1312) runs, and it is the same placement `test_repo_tools_tests_gate.py`
argues for.

chip-AGNOSTIC: no IC, vendor, SKU or process appears here.
"""
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_LAND = _ROOT / "tools" / "gatekeeper-land.sh"
_EMIT = _ROOT / "tools" / "ci" / "hygiene_land_lines.py"
_FN = "run_hygiene_tier"
_PREFIX = "repo hygiene gates :: "
# Bounded far below the 180 s the landing harness runs pytest with, so a hang
# fails THIS test rather than taking the session and every other verdict in it.
_BOUND_S = 30


def _extract_fn(name):
    """Pull `name() { ... }` out of the script, brace-matched at column 0."""
    src = _LAND.read_text().splitlines()
    start = next(i for i, l in enumerate(src) if l.startswith(f"{name}() {{"))
    end = next(i for i in range(start + 1, len(src)) if src[i] == "}")
    return "\n".join(src[start:end + 1])


def _run_tier(tmp_path, record, gate_rc=0):
    """Execute the REAL `run_hygiene_tier` over a stub hygiene script.

    `record` is what the stub writes to the `--summary-json` path (a dict, or
    a raw string for the malformed cases, or None to write nothing at all).
    Returns (FAILED, combined output).
    """
    root = tmp_path / "repo"
    (root / "tools" / "ci").mkdir(parents=True)
    # The emitter under test is the SHIPPED one, not a copy: a fixture copy
    # would keep passing after the real file changed.
    (root / "tools" / "ci" / "hygiene_land_lines.py").symlink_to(_EMIT)

    if record is None:
        body = ""
    elif isinstance(record, str):
        body = record
    else:
        body = json.dumps(record)
    # The stub takes `--summary-json PATH` exactly as `_gate_dispatch.sh` does,
    # writes the record there, and exits with the tier's own verdict.
    stub = (root / "tools" / "ci" / "repo_hygiene_gates.sh")
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'set -uo pipefail\n'
        'out=""\n'
        'while [ $# -gt 0 ]; do\n'
        '  case "$1" in --summary-json) out="$2"; shift 2 ;; *) shift ;; esac\n'
        'done\n'
        '[ -n "$out" ] || { echo "stub: no --summary-json" >&2; exit 2; }\n'
        + ("" if record is None else
           "cat > \"$out\" <<'REC'\n" + body + "\nREC\n")
        + f'echo "repo_hygiene_gates: stub verdict"\nexit {gate_rc}\n')
    stub.chmod(0o755)

    script = (
        "set -uo pipefail\n"
        f'ROOT="{root}"\n'
        "FAILED=0\n"
        + _extract_fn("run") + "\n"
        + _extract_fn(_FN) + "\n"
        + f"{_FN}\n"
        'echo "FAILED=$FAILED"\n'
    )
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       cwd=str(root), env=env, timeout=_BOUND_S)
    out = p.stdout + p.stderr
    # From STDOUT and anchored per line: the emitter's refusal goes to stderr,
    # which the concatenation above puts after it, so an end-anchored search
    # over the combined text would miss the verdict it is looking for.
    m = re.search(r"^FAILED=(\d+)$", p.stdout, re.M)
    assert m, f"the function did not report FAILED=\n{out}"
    return int(m.group(1)), out


def _land_lines(out):
    """Only the lines `landing_merge_verdict.parse_land_log` would read."""
    return [l for l in out.splitlines()
            if re.match(r"^ {2}(PASS|FAIL|SKIP|REPORT) {2}\S", l)]


_THREE = {"listed_only": False, "declared": 3, "gates": [
    {"label": "chip-AGNOSTIC source guard", "state": "PASS", "seconds": 6},
    {"label": "gates are host-independent", "state": "FAIL", "seconds": 225},
    {"label": "PDK registry selectable", "state": "NOT_CHECKED", "seconds": 0}]}


# ── WIRING ────────────────────────────────────────────────────────────────

def test_the_tier_function_exists_and_is_called():
    """A function nobody calls is a comment with syntax."""
    src = _LAND.read_text()
    assert f"{_FN}() {{" in src, f"{_FN} is not defined in gatekeeper-land.sh"
    assert re.search(rf"^{_FN}$", src, re.M), (
        f"{_FN} is defined but never invoked — the hygiene tier would reach "
        f"the landing log as one label again")


def test_the_bare_umbrella_invocation_is_gone():
    """The shape #1498 is about must not come back beside the new one."""
    src = _LAND.read_text()
    assert not re.search(r'^run "repo hygiene gates"', src, re.M), (
        "the hygiene tier is invoked directly by `run` at column 0 again; the "
        "per-gate record is then never asked for and the differential is back "
        "to subtracting one label from one label")


def test_the_record_is_written_outside_the_repository():
    """`suite_write_guard` brackets this tier — a record in the tree is a write
    the gates would be blamed for."""
    fn = _extract_fn(_FN)
    assert "mktemp" in fn, f"the per-gate record is not written to a temp path:\n{fn}"
    assert '"$ROOT"/' not in fn.replace('bash "$ROOT/tools', "").replace(
        'python3 "$ROOT/tools', ""), fn


# ── BEHAVIOUR ─────────────────────────────────────────────────────────────

def test_every_declared_gate_reaches_the_log_by_name(tmp_path):
    failed, out = _run_tier(tmp_path, _THREE, gate_rc=1)
    lines = _land_lines(out)
    assert f"  FAIL  repo hygiene gates" in lines, out
    assert f"  PASS  {_PREFIX}chip-AGNOSTIC source guard" in lines, out
    assert f"  FAIL  {_PREFIX}gates are host-independent" in lines, out
    # rc 2 is "I could not look" and reaches the log as SKIP, never as PASS.
    assert f"  SKIP  {_PREFIX}PDK registry selectable" in lines, out
    assert failed == 1


def test_a_green_tier_still_publishes_its_denominator(tmp_path):
    """The passing gates are the tier's denominator AND the input the
    'silenced rather than fixed' clause needs."""
    rec = {"listed_only": False, "declared": 2, "gates": [
        {"label": "a gate", "state": "PASS", "seconds": 1},
        {"label": "another gate", "state": "PASS", "seconds": 1}]}
    failed, out = _run_tier(tmp_path, rec, gate_rc=0)
    assert failed == 0, out
    assert f"  PASS  {_PREFIX}a gate" in _land_lines(out), out
    assert f"  PASS  {_PREFIX}another gate" in _land_lines(out), out


@pytest.mark.parametrize("record,why", [
    (None, "the record was never written"),
    ("{ not json", "the record is not JSON"),
    ({"listed_only": True, "declared": 1, "gates": [
        {"label": "a", "state": "LISTED", "seconds": 0}]}, "a --list roster"),
    ({"listed_only": False, "declared": 0, "gates": []}, "nothing declared"),
])
def test_a_tier_that_cannot_report_per_gate_fails_and_publishes_nothing(
        tmp_path, record, why):
    """An empty result is not a zero.

    The tier itself is GREEN in every case here (`gate_rc=0`), so the only
    thing that can fail the landing is the missing publication — which is the
    point: a landing that cannot say which gates ran must not be stamped.
    """
    failed, out = _run_tier(tmp_path, record, gate_rc=0)
    subs = [l for l in _land_lines(out) if _PREFIX in l]
    assert subs == [], f"{why}: it published {subs}"
    assert failed == 1, f"{why}: the tier was not failed\n{out}"
    assert "repo hygiene per-gate record" in out, out
