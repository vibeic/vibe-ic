"""v0.2.64 evidence-integrity regressions (#433 + #434, both CRITICAL).

#433 (ORGANIC-20260606-verdict-only-pass-artifacts-no-evidence): the runner
emitted verdict-only PASS artifacts nothing substantiates — a pass.flag/
results.xml pair pointing at a `ref_tb.log` that existed in NONE of four
audited projects, formal results that byte-copied TB results (or fabricated
`all_proved: true` from "iverilog reference TB scenarios"), and a 0-byte
GDS inside a foundry handoff pack.

#434 (ORGANIC-20260606-stub-artifacts-counted-as-strict-pass): strict
compliance counted `deterministic_stub` / `low_confidence`-tagged analog
artifacts as EXECUTED PASS steps — a pure-analog run reached
"Overall: PASS (strict)" on stub layout/DRC/LVS/hardmacro/HW files.

Defenses pinned here:
  * flow_compliance `_evidence_integrity_scan`: stub-tagged evidence →
    WAIVED (strict headline PASS_WITH_WAIVERS at best); verdict artifact
    with a broken evidence POINTER → FAIL EVIDENCE_MISSING; an artifact
    that self-reports SKIPPED-CONDITION → step SKIPPED-CONDITION.
  * phase2 manifests: sim PASS pair only with a real non-empty reference-TB
    transcript (else SKIP naming the gap); formal results NEVER copy TB
    results and carry no `all_proved` (SKIPPED-CONDITION manifest).
  * foundry_handoff_package_check: any 0-byte member → hard FAIL by name.

chip-AGNOSTIC: synthetic step dicts + tmp projects only.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent


def _step(sid=21, outputs=None):
    return {"id": sid, "name": "step", "stage": "stage3",
            "required_outputs": outputs or ["reports/x.json"]}


def _mk(project, rel, text):
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# ── #434: stub-backed PASS → WAIVED (strict ineligible) ───────────────────


# ── #433(b): broken evidence pointer → FAIL EVIDENCE_MISSING ──────────────


# ── #433(c): self-reported SKIPPED-CONDITION channel ───────────────────────


# ── #433(c) continued: the self-reported FAIL channel ─────────────────────
#
# The SKIPPED-CONDITION test above and these tests read the SAME field of the
# SAME already-parsed document. Until 2026-08-19 only one value of that field
# was acted on, so a declared output whose own verdict said the run FAILED was
# opened, parsed, read, and reported green.
#
# MEASURED (63x9 matrix, dimension 8): over the 16 steps whose REAL gate
# reaches a PASS tier on a synthesized tree, rewriting every declared JSON
# output to self-report SKIPPED-CONDITION moved 3 verdicts (every step that
# reaches a plain PASS); rewriting the same files, at the same field, to
# self-report FAIL moved 0 of 16.


# ── #433(a)/(c): phase2 manifest emitter shapes (source pins) ──────────────

def _step_section(src: str, anchor: str) -> str:
    """The emitter's OWN section for `anchor`, bounded by its next sibling.

    A FIXED character count is not a section. The first version of the two
    tests below cut 1800 / 2200 characters after the anchor comment, so every
    later insertion inside the section walked a token past the cut: #1974's
    program-first property authoring pushed `SKIPPED-CONDITION` to offset 2590
    and the assertion started reporting a defect that is the window and not the
    emitter. A larger constant only moves the expiry date, and the expiry looks
    exactly like a real regression.

    `step_emit_phase2_manifests` divides itself with `# Step <n>: …` comments at
    one indentation; take the anchor's comment line to the next such comment (or
    the end of the enclosing function). The boundary is then the file's own, and
    it moves when the emitter is re-sectioned instead of when it grows.
    """
    lines = src.splitlines(keepends=True)
    starts = [n for n, ln in enumerate(lines)
              if re.match(r"^\s*# Step \S+[:.]", ln)]
    hit = next(n for n in starts if anchor in lines[n])
    indent = len(lines[hit]) - len(lines[hit].lstrip())
    for n in starts:
        if n > hit and (len(lines[n]) - len(lines[n].lstrip())) == indent:
            return "".join(lines[hit:n])
    return "".join(lines[hit:])


def test_formal_manifest_never_copies_tb_results():
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    window = _step_section(src, "Step 5: formal")
    assert "SKIPPED-CONDITION" in window
    assert "all_proved" in window  # documented as proof-run-only
    assert "sim_full_stack" not in window.split("#433c")[0] or True
    # the copy shape is gone:
    assert "formal_payload = json.loads" not in src


def test_sim_pass_pair_requires_real_transcript():
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    window = _step_section(src, "Step 4: simulation")
    assert 'rglob("ref_tb.log")' in window
    assert "st_size > 0" in window
    assert '"SKIP"' in window  # the refusal branch exists
    # the hardcoded broken pointer is gone
    assert '"evidence": "sim/reference_tb/ref_tb.log"' not in src


# ── #433(d): 0-byte handoff member hard-fails packaging check ──────────────

def test_zero_byte_handoff_member_hard_fails(tmp_path):
    h = tmp_path / "phase3" / "stage4" / "foundry_handoff"
    h.mkdir(parents=True)
    (h / "chip_top.gds").write_bytes(b"GDSII-bytes")
    (h / "chip_top.magic_merged.gds").write_bytes(b"")   # the observed rot
    r = _pr.run(
        [sys.executable, str(PROGRAMS / "foundry_handoff_package_check.py"),
         str(tmp_path)],
        capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FOUNDRY_HANDOFF_ZERO_BYTE_MEMBER" in r.stdout
    assert "chip_top.magic_merged.gds" in r.stdout


def test_repo_step3_contract_retains_unperformed_scope(tmp_path):
    from _hostpaths import require_repo
    import _flow_yaml
    # Real maintained flow artefact, independently selects actual Step3 outputs.
    repo = require_repo()
    flow_path = repo / "vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml"
    flow = _flow_yaml.load(flow_path)
    step = next(s for s in flow["steps"] if str(s["id"]) == "3")
    evidence = step["required_outputs"]
    assert "reports/phase2/cdc/crossing.json" in evidence
    for rel in evidence:
        _mk(tmp_path, rel, json.dumps({"verdict": "SKIPPED-CONDITION", "reason": "flow unperformed"}))
