"""#614 — a SKIP was published as "the merged layout does not match the schematic".

`mixed_signal_merge_check` turned ANY non-PASS top-level LVS verdict into a
statement about the design, including `SKIP` — which by construction means NO
COMPARISON WAS PERFORMED.

Measured on a real run, where the producer honestly declined (that is #601
working as intended):

    {"verdict": "SKIP",
     "reason": "project dir is not reachable inside container 'vibeic-eda' ..."}

M1 then published:

    top-level LVS verdict 'SKIP' — the merged layout does not match the schematic

A statement about the ENVIRONMENT, published as a statement about the DESIGN.
And in `merge.json` it was indistinguishable from a real mismatch: the same
producer, run where it CAN see the project, returns FAIL with `compared: true`
and a netgen report — a materially different fact flattened into one message.

THE SECOND HALF IS WORSE, and the issue was right to want them decided
together. `main()` writes `top_lvs.json` on a SKIP — deliberately, so a skip
leaves verdict evidence (C5), which is correct — and the write was
UNCONDITIONAL. `flow_compliance_check` invokes the producer with the DEFAULT
container, so on any host where the run root is not bind-mounted under that name
the audit REPLACED a computed FAIL with a capability-gap SKIP, and the gate then
published that SKIP as a design mismatch.

Both properties are kept: the skip still leaves evidence, beside the comparison
rather than on top of it.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


GATE_SRC = (_PROGRAMS / "mixed_signal_merge_check.py").read_text(encoding="utf-8")
PROD_SRC = (_PROGRAMS / "mixed_signal_top_lvs_run.py").read_text(encoding="utf-8")


def _project(tmp_path, top_lvs):
    d = tmp_path / "reports" / "analog" / "mixed_signal"
    d.mkdir(parents=True)
    (d / "top_lvs.json").write_text(json.dumps(top_lvs), encoding="utf-8")
    g = tmp_path / "phase3" / "mixed_signal"
    g.mkdir(parents=True)
    (g / "top_merged.gds").write_bytes(b"\x00\x06\x00\x02\x00\x07")
    return tmp_path


def _run_gate(project):
    """(rc, report). The FINDINGS live in the JSON, not on stdout — the first
    version of these tests asserted on stdout, which prints only the verdict,
    so they were reading a channel the message never travels on."""
    out = project / "gate.json"
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "mixed_signal_merge_check.py"),
         str(project), "--json", str(out)],
        capture_output=True, text=True, timeout=60)
    rep = json.loads(out.read_text()) if out.is_file() else {}
    return r.returncode, rep


def _messages(rep):
    return " ".join(f.get("message", "") + " " + f.get("rule", "")
                    for f in (rep.get("findings") or []))


# ── the gate no longer calls an absent comparison a mismatch ────────────────
def test_a_skip_is_reported_as_not_run_not_as_a_mismatch(tmp_path):
    p = _project(tmp_path, {"verdict": "SKIP",
                            "reason": "project dir is not reachable inside "
                                      "container 'vibeic-eda'"})
    _rc, rep = _run_gate(p)
    msg = _messages(rep)
    assert "does not match the schematic" not in msg, msg
    assert "MERGE_LVS_NOT_RUN" in msg, msg


def test_the_producers_reason_travels_verbatim(tmp_path):
    p = _project(tmp_path, {"verdict": "SKIP",
                            "reason": "tools missing in container: netgen"})
    _rc, rep = _run_gate(p)
    assert "tools missing in container: netgen" in _messages(rep)


def test_a_skip_is_still_not_a_pass(tmp_path):
    """LOAD-BEARING. Correcting the WORDING must not turn a step that returned
    no verdict into a passing one."""
    p = _project(tmp_path, {"verdict": "SKIP", "reason": "x"})
    assert _run_gate(p)[0] != 0


def test_a_real_mismatch_still_says_so(tmp_path):
    """THE ACCEPT CASE. A genuine FAIL, with a comparison behind it, must keep
    the sentence that names the design."""
    p = _project(tmp_path, {"verdict": "FAIL",
                            "lvs_report": "reports/analog/lvs.rpt"})
    rc, rep = _run_gate(p)
    assert "does not match the schematic" in _messages(rep)
    assert rc != 0


def test_a_pass_is_unchanged(tmp_path):
    p = _project(tmp_path, {"verdict": "PASS",
                            "lvs_report": "reports/analog/lvs.rpt"})
    assert _run_gate(p)[0] == 0


# ── a non-result must not displace a result ────────────────────────────────
def test_the_producer_preserves_a_completed_comparison():
    """The dangerous half: an audit-invoked SKIP overwrote a computed verdict.
    Pinned on the source because reaching the write needs a container."""
    seg = PROD_SRC[PROD_SRC.index('if rep.get("verdict") == "SKIP":'):][:2600]
    assert "_compared" in seg, "the write is unconditional again"
    assert "top_lvs_skipped.json" in seg, (
        "a skip that cannot be recorded beside the comparison ends up on top "
        "of it")
    assert "did_not_overwrite" in seg, (
        "the caller is not told that its skip did not become the verdict")


def test_the_skip_still_leaves_evidence_when_nothing_was_compared():
    """C5's reason stands: a SKIP that writes NOTHING is indistinguishable from
    a producer that never ran. The else-branch must still write."""
    seg = PROD_SRC[PROD_SRC.index('if rep.get("verdict") == "SKIP":'):][:2600]
    assert "else:" in seg and "_ev.write_text" in seg


def test_the_preservation_keys_on_a_completed_comparison_not_on_the_word_pass():
    """A prior FAIL that DID compare is a result too, and must be preserved as
    firmly as a PASS."""
    seg = PROD_SRC[PROD_SRC.index('if rep.get("verdict") == "SKIP":'):][:2600]
    assert '_prior.get("lvs_report")' in seg, (
        "preservation keyed on the verdict WORD would discard a real FAIL")


def test_the_gate_still_distinguishes_absent_lvs_from_skipped_lvs():
    """Three different states, three different rules: no result at all, a
    result that says 'not run', and a result that says 'mismatch'."""
    for rule in ("MERGE_NOT_LVS_SUBSTANTIATED", "MERGE_LVS_NOT_RUN",
                 "MERGE_LVS_FAIL", "MERGE_LVS_OK"):
        assert rule in GATE_SRC, f"{rule} is gone"
