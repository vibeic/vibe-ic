"""vibe-ic#800 — an artefact's `emitted_by` must be READ from the manifest.

THE DEFECT
==========
Twenty-nine emit sites across twenty-nine programs stamped the release that
produced an artefact as a STRING LITERAL: `"pnr_doctor v0.1.96"`,
`"phase1_post_process.emit_l_doc_skeleton v0.1.51"`, `"_Emitted by
\\`sta_triage_classify.py\\` (v0.1.50)._"`. The plugin shipped 1.9.78 and 1436
tracked artefacts under `benchmark-data/` carry the stale claim.

WHY THE TESTS BELOW ARE SHAPED THIS WAY
=======================================
Swapping `v0.1.50` for `v1.9.78` passes any test that pins a version string,
and re-creates the defect at the next bump — so no test here may be satisfiable
by a constant. Every value assertion drives the emitter against a manifest
declaring an ABSURD version (`7.0.1`, `42.13.9`) and requires the emitted value
to FOLLOW it. Two different absurd versions are used because one constant can
satisfy one of them.

The seam is `plugin_manifest_discovery._THIS_PLUGIN_ROOT`, read at CALL time
rather than import time precisely so a test can point it somewhere else.
"""
from __future__ import annotations

import ast
import importlib
import json
import re
from pathlib import Path
from typing import Optional

import pytest

import plugin_manifest_discovery as pmd

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN_ROOT = _PROGRAMS.parent
_PLUGIN_JSON = _PLUGIN_ROOT / ".claude-plugin" / "plugin.json"

# Two absurd versions. No single constant satisfies both.
_ABSURD_A = "7.0.1"
_ABSURD_B = "42.13.9"


def _manifest_at(tmp_path: Path, version: str) -> Path:
    """A minimal plugin tree whose plugin.json declares `version`."""
    root = tmp_path / f"plugin_{version.replace('.', '_')}"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": version}), encoding="utf-8")
    return root


@pytest.fixture()
def absurd_a(tmp_path, monkeypatch):
    monkeypatch.setattr(pmd, "_THIS_PLUGIN_ROOT", _manifest_at(tmp_path, _ABSURD_A))
    return _ABSURD_A


@pytest.fixture()
def absurd_b(tmp_path, monkeypatch):
    monkeypatch.setattr(pmd, "_THIS_PLUGIN_ROOT", _manifest_at(tmp_path, _ABSURD_B))
    return _ABSURD_B


# ─────────────────────────────────────────────────────────────────────
# 1. The resolver itself
# ─────────────────────────────────────────────────────────────────────
class TestResolver:
    def test_running_version_is_the_shipped_manifest_value(self):
        """Not a literal in this test either — read the manifest and compare."""
        shipped = json.loads(_PLUGIN_JSON.read_text(encoding="utf-8"))["version"]
        assert pmd.running_plugin_version() == shipped

    def test_running_version_follows_an_absurd_manifest(self, absurd_a):
        assert pmd.running_plugin_version() == "7.0.1"

    def test_running_version_follows_a_second_absurd_manifest(self, absurd_b):
        assert pmd.running_plugin_version() == "42.13.9"

    def test_emitted_by_is_tool_space_v_version(self, absurd_a):
        assert pmd.emitted_by("some_tool") == "some_tool v7.0.1"

    def test_emitted_by_note_is_parenthesised(self, absurd_b):
        assert pmd.emitted_by("signoff_ladder_run", "release-gate-wired") == \
            "signoff_ladder_run v42.13.9 (release-gate-wired)"

    def test_unreadable_manifest_is_visibly_non_data(self, tmp_path, monkeypatch):
        """No plausible default. A version nobody read is never invented.

        ONE marker for one condition: the eighteen sites that interpolate
        `running_plugin_version()` directly must render the same sentinel the
        module documents, not an empty string that reads as `(v).`"""
        monkeypatch.setattr(pmd, "_THIS_PLUGIN_ROOT", tmp_path / "nowhere")
        assert pmd.running_plugin_version() == "UNRESOLVED"
        assert pmd.emitted_by("some_tool") == "some_tool vUNRESOLVED"

    def test_unresolved_renders_the_same_at_a_direct_interpolation_site(
            self, tmp_path, monkeypatch):
        """The prose emitters build `(v{running_plugin_version()})` themselves,
        so they are where an empty sentinel would have leaked."""
        monkeypatch.setattr(pmd, "_THIS_PLUGIN_ROOT", tmp_path / "nowhere")
        mod = importlib.import_module("sta_triage_classify")
        md = mod.report_to_markdown(mod.build_report([], 0.0, 0.0))
        assert "(vUNRESOLVED)." in md
        assert "(v)." not in md

    def test_unresolved_token_is_not_version_shaped(self):
        """`0.1.33` sorted and compared like a measurement; this must not."""
        assert re.fullmatch(r"\d+\.\d+\.\d+", pmd.UNRESOLVED_VERSION) is None


# ─────────────────────────────────────────────────────────────────────
# 2. The emitters follow the manifest — driven, not read
# ─────────────────────────────────────────────────────────────────────
class TestEmittersFollowTheManifest:
    """Each drives a REAL emit entry point. Asserting `"7.0.1" in value` would
    be satisfiable by a hardcoded `7.0.1`, so every assertion here is full
    string equality against a value the manifest alone determines."""

    def test_l_doc_taxonomy_na_stub(self, absurd_a):
        mod = importlib.import_module("l_doc_taxonomy")
        stub = mod.na_stub("digital_arithmetic_primitive",
                           "L26_MECHANICAL_TRANSDUCTION")
        assert stub["emitted_by"] == "l_doc_taxonomy.na_stub v7.0.1"

    def test_l_doc_taxonomy_na_stub_second_version(self, absurd_b):
        mod = importlib.import_module("l_doc_taxonomy")
        stub = mod.na_stub("digital_arithmetic_primitive",
                           "L26_MECHANICAL_TRANSDUCTION")
        assert stub["emitted_by"] == "l_doc_taxonomy.na_stub v42.13.9"

    def test_phase1_post_process_skeleton(self, absurd_a):
        mod = importlib.import_module("phase1_post_process")
        sk = mod.emit_l_doc_skeleton("L20_DFT_SCAN_TOPOLOGY")
        assert sk["emitted_by"] == \
            "phase1_post_process.emit_l_doc_skeleton v7.0.1"

    def test_hold_fix_planner_json_and_markdown(self, absurd_b):
        mod = importlib.import_module("hold_fix_planner")
        plan = mod.build_plan([])
        assert plan["emitted_by"] == "hold_fix_planner v42.13.9"
        assert "_Emitted by `hold_fix_planner.py` (v42.13.9)._" in \
            mod.plan_to_markdown(plan)

    def test_ir_drop_triage_json_and_markdown(self, absurd_a):
        mod = importlib.import_module("ir_drop_triage_classify")
        t = mod.build_triage([])
        assert t["emitted_by"] == "ir_drop_triage_classify v7.0.1"
        assert "_Emitted by `ir_drop_triage_classify.py` (v7.0.1)._" in \
            mod.triage_to_markdown(t)

    def test_mpw_precheck_result_gate_attribution_carries_no_version(self):
        """The constant names the TOOL only — the release half is never
        restated. `mpw_precheck_result_gate v1.2.76` was the defect."""
        mod = importlib.import_module("mpw_precheck_result_gate")
        assert mod.ATTRIBUTION == "mpw_precheck_result_gate"

    def test_protocol_timeline_tb_carries_the_manifest_version(self, absurd_a):
        mod = importlib.import_module("protocol_timeline_assert_gen")
        tb = mod.emit_tb(mod.TurnaroundParams(
            clock_period_ns=10, delimiter_typical_ns=100,
            t_turnaround_min_ns=8000, t_turnaround_max_ns=12000,
            tx_start_signal="tx_start", spec_section="DS 8.3"))
        assert ("Emitted by `protocol_timeline_assert_gen.py` "
                "(Vibe-IC plugin v7.0.1).") in tb
        assert "__PLUGIN_VERSION__" not in tb

    def test_protocol_spec_extract_merge_path(self, absurd_a, tmp_path):
        """The `fill_skeletons` merge builds its attribution with an f-string
        and assigns it by subscript — the two shapes the first source scan did
        not see. Driving it is what found the site."""
        mod = importlib.import_module("phase1_protocol_spec_extract")
        docs = tmp_path / "phase1" / "generated_docs"
        docs.mkdir(parents=True)
        (docs / "L14_PROTOCOL_VERSIONING.json").write_text(
            json.dumps({"applicability": "APPLICABLE"}), encoding="utf-8")
        mod.fill_skeletons(
            tmp_path,
            "16 June 2003       A     Non-Confidential   First release\n")
        got = json.loads(
            (docs / "L14_PROTOCOL_VERSIONING.json").read_text(encoding="utf-8"))
        assert got["extracted_by"] == \
            "phase1_protocol_spec_extract.extract_l14_* v7.0.1"

    def test_analog_oracle_comparator_version(self, absurd_b):
        mod = importlib.import_module("analog_oracle_compare")
        src = (_PROGRAMS / "analog_oracle_compare.py").read_text(encoding="utf-8")
        assert '"comparator_version": _pmd.emitted_by(' in src
        assert mod._pmd.emitted_by("analog_oracle_compare") == \
            "analog_oracle_compare v42.13.9"

    def test_lvs_netgen_setup_header(self, absurd_b):
        mod = importlib.import_module("lvs_netgen_setup_emit")
        txt = mod.build_supplementary_setup_tcl("sky130A")
        assert "# Vibe-IC plugin v42.13.9 — supplementary Netgen LVS setup" \
            in txt


# ─────────────────────────────────────────────────────────────────────
# 3. The source-level gate: no emit site may RESTATE the version
# ─────────────────────────────────────────────────────────────────────
# Every program that asks the manifest for the running version. A literal set,
# compared by set equality: a NEW emitter that reads the version must be added
# here, and a program that stops reading it must be removed. Both directions
# fail loudly rather than drifting.
_VERSION_READING_PROGRAMS = {
    "aid_class_rtl_gen",
    "analog_oracle_compare",
    "caravel_integration_runner",
    "caravel_wrapper_emit",
    "drc_fix_planner",
    "eco_status_gen",
    # The audit artefact's own `version` field. It said "0.119.62" on all 28
    # tracked audits, across every release from 1.0.0 to 1.9.79 — #800's scan
    # never saw it because the key is `version`, which is not one of
    # _ATTRIBUTION_KEYS.
    "flow_compliance_check",
    "foundry_handoff_pack_gen",
    "hold_fix_planner",
    "ir_drop_triage_classify",
    "l_doc_parity_diff",
    "l_doc_taxonomy",
    "lvs_netgen_setup_emit",
    "lvs_triage_classify",
    "mpw_precheck_cleanup",
    "mpw_precheck_result_gate",
    "oracle_vector_gen",
    "phase1_doc_one_shot_runner",
    "phase1_post_process",
    "phase1_protocol_spec_extract",
    "phase1_verify_aggregate",
    "phase2_verify_aggregate",
    "phase3_verify_aggregate",
    "pnr_doctor",
    "ppa_predict_aggregate",
    "protocol_timeline_assert_gen",
    "protocol_turnaround_audit",
    "rtl_review_aggregate",
    "signoff_ladder_run",
    "signoff_waiver_emit",
    "signoff_waiver_md_emit",
    "sta_triage_classify",
    "synth_doctor",
    # The LIVE open-MPW submission gate (#1744). Its verdict JSON is read back
    # by the sign-off ladder, so the release that produced a refusal has to be
    # recoverable from the artefact rather than from whoever remembers the run.
    "tapeout_readiness_check",
}

# The ONLY whole-file exemption. Every other candidate was checked with
# exemptions OFF and produces zero findings, so exempting it would have bought
# nothing and permanently blinded the gate to that file — including
# `design_one_shot_runner`, one of the largest emitters in the tree.
# `caravel_wrapper_harden_driver` and `xor_layout_check` say `v1`, a FORMAT
# generation; `_VERSION_TOKEN` does not match a bare major, so they need no
# exemption to stay quiet, and they DO get scanned the day someone writes
# `v1.2.3` there. `eco_status_gen` was exempted in the first draft as a
# "program-internal tool version"; that reasoning does not survive contact —
# `1.1.0` is version-shaped exactly like a release — so it is FIXED instead.
_NOT_A_PLUGIN_RELEASE_CLAIM = {
    # OWNED BY A CONCURRENT AGENT while #800 was in flight, so its sites are
    # recorded as residual rather than edited under another agent.
    #
    # MEASURED, not estimated: EIGHT sites, at TWO different stale releases —
    # six at v1.6.36 (:25475 :27722 :28377 :29024 :31397 :31439) and two at
    # v1.6.52 (:35683 :35698). The first draft of this comment said "five … at
    # v1.6.36", which understated the count and named one of the two versions;
    # a residual recorded at 5/8 its real size is what a later reader trusts.
    # Command that produced the list:
    #     grep -n "phase3_one_shot_runner v[0-9]" programs/phase3_one_shot_runner.py
    "phase3_one_shot_runner",
}

# A version-shaped token: `v` + two-or-three components, or a bare three. A bare
# TWO-component number is NOT matched, so `"schema_version": "1.0"` and an
# external citation like `IEEE 802.3` cannot trip it. The `v1.1` form is in
# because `foundry_handoff_pack_gen` shipped `"generated_by":
# "foundry_handoff_pack_gen v1.1"` — a real base offender that the original
# three-component-only token did not see.
_VERSION_TOKEN = re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b|\b\d+\.\d+\.\d+\b")
# `extracted_by` and `comparator_version` are on this list because the first
# sweep for #800 missed them: the issue named `emitted_by`, so a grep for that
# key found five `extracted_by` sites and one `comparator_version` — the same
# claim under a different noun — only after a test that had pinned one of the
# literals went red. A gate keyed on ONE spelling of a field is how the second
# spelling survives, so this names the family.
_ATTRIBUTION_KEYS = ("emitted_by", "generated_by", "extracted_by",
                     "comparator_version")


def _docstring_ids(tree: ast.AST) -> set:
    """`id()` of every module / class / function docstring node.

    Docstrings are PROSE ABOUT the program — they cite the wave a helper was
    introduced in, quote historical defects, and reference other releases. None
    of that is stamped into an artefact, so scanning them would drown the real
    finding in ~200 legitimate mentions."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


# Names whose module-level constant IS an attribution by construction, so the
# constant is scanned wherever it is defined rather than only where it is used.
_ATTRIBUTION_CONST_RE = re.compile(r"^_?(ATTRIBUTION|EMITTED_BY|GENERATED_BY)$")


def _module_string_consts(tree: ast.AST) -> dict:
    """`{NAME: "value"}` for every module-level `NAME = "<string literal>"`.

    THE SHAPE THE FIRST DRAFT COULD NOT SEE. At e3aa9b126,
    `mpw_precheck_result_gate.py:57` held
    ``ATTRIBUTION = "mpw_precheck_result_gate v1.2.76"`` and used it at
    ``{"emitted_by": ATTRIBUTION}``. The value at the emit site is an
    ``ast.Name``, not a string, so a scan that only inspects string nodes scored
    that file ZERO — a live offender, invisible. It was converted by hand and
    pinned by a bespoke test, which fixes one file and leaves the SHAPE
    unguarded: re-introducing it anywhere (`_PNR_ATTR = "pnr_doctor v1.9.78"`
    used at one of pnr_doctor's two sites) passed the whole suite green.
    Resolving the constant is what closes it.
    """
    out = {}
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _literal_pieces(node: ast.AST, consts: Optional[dict] = None):
    """Every string LITERAL reachable from `node`.

    Covers three shapes beyond a plain constant:
      * f-string — `f"…extract_{code}_* v0.1.51"` is a JoinedStr whose version
        lives in a constant beside a FormattedValue;
      * `%` / `+` / `.format()` — walked, so their literal halves are seen;
      * a bare NAME resolved through `consts` (see `_module_string_consts`).
    """
    consts = consts or {}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
        elif isinstance(sub, ast.Name) and sub.id in consts:
            out.append(consts[sub.id])
    return out


def _attribution_string_literals(path: Path):
    """(lineno, value) for every EMITTED string constant that attributes an
    artefact to this tool: the value of an `emitted_by` / `generated_by` dict
    key, or an `_Emitted by …` / `Auto-generated by …` / `Vibe-IC plugin v…`
    line. Docstrings excluded — see `_docstring_ids`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    skip = _docstring_ids(tree)
    consts = _module_string_consts(tree)
    out = []

    # SHAPE 0 — a module-level constant that IS an attribution by its name.
    # Scanned at its DEFINITION so the file is a finding even if the use site
    # is a form no other shape here reaches.
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name) and _ATTRIBUTION_CONST_RE.match(t.id):
                    out.append((node.lineno, node.value.value))

    for node in ast.walk(tree):
        # SHAPE 1 — `{"emitted_by": <value>}`. `<value>` may be a literal, an
        # f-string, or a NAME resolved through the module constants.
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in _ATTRIBUTION_KEYS:
                    for piece in _literal_pieces(v, consts):
                        out.append((getattr(v, "lineno", node.lineno), piece))
        # SHAPE 2 — `d["emitted_by"] = <value>`. Here because the dict-literal
        # scan alone missed two live sites (`ppa_predict_aggregate`, and a
        # `fill_skeletons` merge that builds the value with an f-string), and
        # one of them survived the first sweep.
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if not (isinstance(t, ast.Subscript)
                        and isinstance(t.slice, ast.Constant)
                        and t.slice.value in _ATTRIBUTION_KEYS):
                    continue
                for piece in _literal_pieces(node.value, consts):
                    out.append((node.lineno, piece))
        # SHAPE 3 — `payload.setdefault("emitted_by", <value>)` /
        # `.get("emitted_by", <value>)`. `phase1_doc_one_shot_runner:9827` was
        # exactly this and was fixed by hand, unseen by shapes 1 and 2.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("setdefault", "get") \
                and len(node.args) == 2 \
                and isinstance(node.args[0], ast.Constant) \
                and node.args[0].value in _ATTRIBUTION_KEYS:
            for piece in _literal_pieces(node.args[1], consts):
                out.append((node.lineno, piece))
        # SHAPE 4 — prose. LINE-scoped, because a multi-line RTL/Tcl template
        # legitimately contains version-shaped tokens (parameters, timescales)
        # far from its "Generated by" header.
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in skip:
            # KNOWN EVASION of this shape: a version that sits on a DIFFERENT
            # line of the same template from the "generated by" phrase — how
            # `aid_class_rtl_gen`'s `**Plugin version**: vibe-ic v0.119.78+`
            # got past it. That site was fixed by hand. Shapes 1-3 are the
            # structural cover; this one is best-effort prose.
            for line in node.value.splitlines():
                low = line.lower()
                if ("emitted by" in low or "auto-generated by" in low
                        or "generated by" in low or "vibe-ic plugin v" in low):
                    out.append((node.lineno, line))
    return out


class TestNoEmitSiteRestatesTheVersion:
    def test_no_attribution_literal_states_a_version(self):
        offenders = []
        for py in sorted(_PROGRAMS.glob("*.py")):
            if py.stem in _NOT_A_PLUGIN_RELEASE_CLAIM:
                continue
            for lineno, val in _attribution_string_literals(py):
                if _VERSION_TOKEN.search(val):
                    offenders.append(f"{py.name}:{lineno}: {val.strip()[:90]}")
        assert offenders == [], (
            "an attribution string states a version literal instead of "
            "reading it from the manifest (#800):\n  " + "\n  ".join(offenders))

    def test_the_set_of_version_reading_programs_is_pinned(self):
        found = set()
        for py in sorted(_PROGRAMS.glob("*.py")):
            src = py.read_text(encoding="utf-8")
            if "_pmd.emitted_by(" in src or "_pmd.running_plugin_version()" in src:
                found.add(py.stem)
        assert found == _VERSION_READING_PROGRAMS, (
            "the set of programs that READ the plugin version has changed.\n"
            f"  newly reading, add to _VERSION_READING_PROGRAMS: "
            f"{sorted(found - _VERSION_READING_PROGRAMS) or 'none'}\n"
            f"  no longer reading, remove from it: "
            f"{sorted(_VERSION_READING_PROGRAMS - found) or 'none'}\n"
            "This set is pinned so a new emitter cannot appear silently (#800); "
            "updating it is the intended response, not a failure.")

    # ── bidirectional control for the module-constant shape (F1) ──
    # A gate is only evidence if it can be shown to FIRE. These two synthesise
    # the exact base defect — `ATTRIBUTION = "<tool> v1.2.76"` used at
    # `{"emitted_by": ATTRIBUTION}` — and require a finding, then require
    # silence once the constant carries no version. Without the positive half,
    # "0 offenders" is indistinguishable from a scanner that reads nothing.
    _CONST_SHAPE_OFFENDER = (
        'ATTRIBUTION = "mpw_precheck_result_gate v1.2.76"\n'
        'def as_dict():\n'
        '    return {"emitted_by": ATTRIBUTION}\n'
    )
    _CONST_SHAPE_CLEAN = (
        'ATTRIBUTION = "mpw_precheck_result_gate"\n'
        'def as_dict():\n'
        '    return {"emitted_by": _pmd.emitted_by(ATTRIBUTION)}\n'
    )

    def _scan(self, tmp_path, src, name="probe.py"):
        p = tmp_path / name
        p.write_text(src, encoding="utf-8")
        return [f"{lineno}: {v}" for lineno, v in _attribution_string_literals(p)
                if _VERSION_TOKEN.search(v)]

    def test_module_constant_shape_is_caught(self, tmp_path):
        """POSITIVE control — the shape the first draft scored 0 on."""
        assert self._scan(tmp_path, self._CONST_SHAPE_OFFENDER) != []

    def test_module_constant_shape_is_silent_once_fixed(self, tmp_path):
        """NEGATIVE control — no finding on the shape as it now ships."""
        assert self._scan(tmp_path, self._CONST_SHAPE_CLEAN) == []

    def test_two_component_version_is_caught(self, tmp_path):
        """`foundry_handoff_pack_gen v1.1` — a real base offender the original
        three-component-only token did not match."""
        assert self._scan(
            tmp_path,
            'D = {"generated_by": "foundry_handoff_pack_gen v1.1"}\n') != []

    def test_setdefault_shape_is_caught(self, tmp_path):
        """`phase1_doc_one_shot_runner:9827` was this, and was fixed by hand."""
        assert self._scan(
            tmp_path,
            'def f(p, n):\n'
            '    p.setdefault("emitted_by", f"extract.{n} v0.1.62")\n') != []

    def test_bare_two_component_number_is_not_a_finding(self, tmp_path):
        """`"schema_version": "1.0"` is the DOCUMENT schema, not a release, and
        must not be swept up by widening the token to reach `v1.1`."""
        assert self._scan(
            tmp_path,
            'D = {"emitted_by": "tool", "schema_version": "1.0"}\n') == []

    def test_the_version_is_read_from_exactly_one_module(self):
        """No emitter may open plugin.json itself — that is a second reader,
        and two readers are how the two drift apart."""
        offenders = []
        for name in sorted(_VERSION_READING_PROGRAMS):
            src = (_PROGRAMS / f"{name}.py").read_text(encoding="utf-8")
            if "plugin.json" in src:
                offenders.append(name)
        assert offenders == []
