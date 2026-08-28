#!/usr/bin/env python3
"""A manifest may record `status:"PASS"` only when the metrics that prove the
work happened are present. Absent -> INCONCLUSIVE. Never PASS.

MEASURED DEFECT this pins. `eda_sta` returned success:true and wrote manifest
`status:"PASS"` while openroad exited 0 having linked NO design at all
(read_verilog ORD-2010, link_design STA-1570, every report STA-1571).
`writeManifest` looked only at `result.success`, and the `wns`/`tns` it recorded
were `null` because there was nothing to parse. A run that measured nothing was
recorded as proven-good. `sta_mcorner` has the same shape one level up: with
every corner's `wns` null, `timing_met` is null, `overall_pass` is never set
false, and the manifest records PASS for corners nobody measured.

Modelled on OpenROAD-flow-scripts' `checkMetadata.py`, where a required metric
that is ABSENT is a hard stop rather than a default.

The pair that matters, and both halves are load-bearing:
  * a PASS whose required metric is absent  -> INCONCLUSIVE (red pole)
  * a PASS whose required metrics are there -> still PASS  (green pole)
A check that cannot go red is not a check; one that fires on everything is a
refusal machine.

Runtime checks skip if node is not on PATH; the static wiring checks do not.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import sys
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

MCP_ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = MCP_ROOT / "src" / "index.js"
GATE_MJS = MCP_ROOT / "src" / "lib" / "manifest_metrics.mjs"
NODE = shutil.which("node")


# ── A. static checks on the wiring ─────────────────────────────────────────

def test_gate_module_exists() -> None:
    assert GATE_MJS.is_file(), f"{GATE_MJS} is the declaration; it must ship"


def test_index_routes_every_manifest_write_through_the_gate() -> None:
    """`writeManifest` is the single choke point for the manifest, so the gate
    is applied there and cannot be forgotten at a new call site."""
    src = INDEX_JS.read_text()
    assert 'from "./lib/manifest_metrics.mjs"' in src
    assert "gateManifestEntry" in src
    # The entry is spread through the gate, never raw.
    assert "...gateManifestEntry(entry)," in src
    body = src[src.index("function writeManifest("):]
    body = body[: body.index("\n}\n")]
    assert "...entry," not in body, (
        "writeManifest spreads the raw entry — a PASS with no metrics would "
        "reach the manifest ungated")


def test_sta_and_sta_mcorner_are_declared() -> None:
    """The two steps the measured bug was found in must carry a declaration."""
    decl = GATE_MJS.read_text()
    assert "sta:" in decl and '{ key: "wns" }' in decl and '{ key: "tns" }' in decl
    assert "sta_mcorner:" in decl and "everyCornerMeasured" in decl


# ── B. runtime no-leak proof on the gate module ────────────────────────────

_HARNESS = r"""
import { gateManifestEntry, REQUIRED_METRICS, missingRequiredMetrics }
  from "%s";
const entry = JSON.parse(process.argv[1]);
if (entry.__dump_table__) {
  const out = {};
  for (const [step, specs] of Object.entries(REQUIRED_METRICS))
    out[step] = specs.map((s) => s.key);
  console.log(JSON.stringify(out));
} else {
  console.log(JSON.stringify(gateManifestEntry(entry)));
}
"""


def _gate(entry: dict) -> dict:
    src = _HARNESS % GATE_MJS.as_uri()
    r = _pr.run(
        [NODE, "--input-type=module", "-e", src, json.dumps(entry)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _table() -> dict:
    return _gate({"__dump_table__": True})


pytestmark = pytest.mark.skipif(
    not INDEX_JS.is_file(), reason="mcp-eda/src/index.js not present")


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_sta_without_wns_is_inconclusive_not_pass() -> None:
    """RED POLE — the measured bug. OpenSTA linked nothing, so there is no wns
    and no tns to record. That is not a passing timing run."""
    out = _gate({"step": "sta", "status": "PASS", "tool": "OpenSTA",
                 "wns": None, "tns": None})
    assert out["status"] == "INCONCLUSIVE"
    assert out["status"] != "PASS"
    assert out["missing_metrics"] == ["wns", "tns"]
    assert "wns" in out["inconclusive_reason"]


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_sta_with_real_numbers_is_still_pass() -> None:
    """GREEN POLE — a genuinely clean run is untouched. Note wns == 0.0: a
    measured zero is a measurement, and must not be mistaken for absence."""
    out = _gate({"step": "sta", "status": "PASS", "tool": "OpenSTA",
                 "wns": 0.0, "tns": 0.0})
    assert out["status"] == "PASS"
    assert "missing_metrics" not in out
    out2 = _gate({"step": "sta", "status": "PASS", "wns": -1.5, "tns": -12.0})
    assert out2["status"] == "PASS"


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_a_real_failure_is_still_a_failure() -> None:
    """CONTROL — the gate only ever downgrades PASS. It must not blind FAIL,
    and it must not launder FAIL into the softer INCONCLUSIVE."""
    out = _gate({"step": "drc", "status": "FAIL", "violations": 12})
    assert out["status"] == "FAIL"
    out = _gate({"step": "sta", "status": "FAIL", "wns": None, "tns": None})
    assert out["status"] == "FAIL"


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_other_verdicts_pass_through_untouched() -> None:
    """A tool's own non-PASS verdict is its own; the gate does not relabel it."""
    for status in ("TIMING_VIOLATED", "SPEC_FAIL", "DEFERRED",
                   "STRUCTURAL_PASS", "MEAS_FAILED", "SUSPICIOUS"):
        out = _gate({"step": "sta", "status": status})
        assert out["status"] == status


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_an_undeclared_step_is_not_gated() -> None:
    """Silence in the table means "no metric declared yet", and an undeclared
    step keeps its PASS. Turning every unlisted step red would be the same
    defect pointed the other way."""
    out = _gate({"step": "ic_search", "status": "PASS", "results_count": 3})
    assert out["status"] == "PASS"


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_sta_mcorner_needs_every_corner_measured() -> None:
    good = {"ss": {"wns": 1.0}, "ff": {"wns": 2.0}}
    assert _gate({"step": "sta_mcorner", "status": "PASS",
                  "corners": good})["status"] == "PASS"
    for bad in ({}, {"ss": {"wns": 1.0}, "ff": {"wns": None}},
                {"ss": {"wns": None}}):
        out = _gate({"step": "sta_mcorner", "status": "PASS", "corners": bad})
        assert out["status"] == "INCONCLUSIVE", bad
    assert _gate({"step": "sta_mcorner", "status": "PASS"})["status"] \
        == "INCONCLUSIVE"


# ── C. the ratchet: this fails if a future change lets a missing required
#      metric write PASS, for ANY declared step, without anyone editing here ──

@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_every_declared_metric_actually_blocks_a_pass() -> None:
    """For every step in the declaration and every metric it requires, dropping
    just that one metric must stop the PASS. If someone later adds a step to
    REQUIRED_METRICS but the gate does not honour it, or relaxes an existing
    entry so an absent metric still passes, this goes red without anyone having
    remembered to extend this file."""
    table = _table()
    assert table, "the declaration is empty — nothing is being required"
    for step, keys in table.items():
        assert keys, f"step {step} declares no required metric"
        full = {"step": step, "status": "PASS"}
        for k in keys:
            full[k] = ({"c1": {"wns": 0.0}} if k == "corners" else 0)
        assert _gate(full)["status"] == "PASS", (
            f"{step}: a fully-measured PASS must survive — {full}")
        for k in keys:
            partial = dict(full)
            partial[k] = None
            out = _gate(partial)
            assert out["status"] == "INCONCLUSIVE", (
                f"{step}: required metric {k!r} is absent and the manifest "
                f"still recorded {out['status']!r}")
            assert k in out["missing_metrics"]
            dropped = {kk: vv for kk, vv in full.items() if kk != k}
            assert _gate(dropped)["status"] == "INCONCLUSIVE", (
                f"{step}: required metric {k!r} missing entirely and the "
                f"manifest still recorded a pass")


# ── D. the parser that decides whether the metric is there at all ──────────
#
# Recorded from a real run in the pinned image
# ghcr.io/vibeic/vibeic-eda@sha256:4ece6c01cddc99903af4f027326f7624b069311f207
# 3a5a0b565d5a9cf649a16 — a sky130 counter through yosys + openroad. These are
# the exact bytes OpenSTA printed.

SLACK_MJS = MCP_ROOT / "src" / "lib" / "sta_slack.mjs"

_CLEAN_TAIL = "         198.45   slack (MET)\n\n\nwns max 0.00\ntns max 0.00\n"
_VIOLATING_TAIL = "tns max -2.19\nwns max -0.65\n"
_UNLINKED_TAIL = (
    "[ERROR ORD-2010] no technology has been read.\nORD-2010\n"
    "[ERROR STA-1570] No network has been linked.\nSTA-1570\n"
    "[ERROR STA-1571] No network has been linked.\nSTA-1571\n")


def _parse(text: str) -> dict:
    src = ('import { parseWns, parseTns } from "%s";\n'
           'const t = JSON.parse(process.argv[1]);\n'
           'console.log(JSON.stringify({wns: parseWns(t), tns: parseTns(t)}));'
           % SLACK_MJS.as_uri())
    r = _pr.run([NODE, "--input-type=module", "-e", src,
                        json.dumps(text)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_index_uses_the_shared_slack_parser() -> None:
    """Both STA sites read slack through one parser. The regex they replaced,
    /wns\\s+([\\d.-]+)/, could not match `wns max 0.00` and so returned null for
    EVERY run — clean, violating and unlinked alike."""
    src = INDEX_JS.read_text()
    assert 'from "./lib/sta_slack.mjs"' in src
    assert "wnsMatch" not in src and "tnsMatch" not in src
    assert src.count("parseWns(result.output)") == 2


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_slack_parser_reads_what_opensta_actually_prints() -> None:
    assert _parse(_CLEAN_TAIL) == {"wns": 0, "tns": 0}
    assert _parse(_VIOLATING_TAIL) == {"wns": -0.65, "tns": -2.19}


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_slack_parser_reports_absence_as_absence() -> None:
    """RED POLE for the parser: a run that linked nothing printed no slack
    line. That is null — NOT MEASURED — and must never be defaulted to 0.0,
    which is exactly what a clean run looks like."""
    assert _parse(_UNLINKED_TAIL) == {"wns": None, "tns": None}
    assert _parse("") == {"wns": None, "tns": None}
    # A sentence that merely contains the word is not a measurement.
    assert _parse("the wns is fine, 0.00 everywhere\n") == \
        {"wns": None, "tns": None}


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_slack_parser_prefers_the_setup_corner_and_reads_bare_form() -> None:
    assert _parse("wns min 5.00\nwns max -0.65\n")["wns"] == -0.65
    assert _parse("wns 1.25\n")["wns"] == 1.25
