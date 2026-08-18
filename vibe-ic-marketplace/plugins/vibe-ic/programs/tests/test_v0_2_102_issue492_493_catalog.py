"""tests/test_v0_2_102_issue492_493_catalog.py — v0.2.102

Covers GitHub issues #492 + #493 (IP-catalog layer), chip-AGNOSTIC.

#492 — synth_safe_params hint for catalog IPs
  (a) the manifest schema gains `synth_safe_params`; the relevant CPU
      (serv) manifest declares the sim=0 hint.
  (b) the serv integration_guide states the sim=0 requirement.
  (c) catalog-glue-author SKILL documents reading synth_safe_params and
      applying them by default (sim-only PLI generate-block case).
  Plus: CatalogMatch carries synth_safe_params + synth_param_overrides()
        returns {param: synth_safe_value}, so a glue-author dry-run /
        source pin shows the param applied.

#493 part 1 — MANDATORY-vs-OPTIONAL extension matcher
  An "cpu_extensions / cpu_isa contains '<ext>'" rule only fires when
  the extension is MANDATORY (base ISA string / required field), not
  when it is an OPTIONAL mention. End-to-end via the real catalog: an
  optional-F project no longer matches the FPU while a mandatory-F ISA
  still does.

#493 part 2 — prune / supersede path in ip_catalog_pull
  prune_catalog_ip removes the pulled files + records a removal-shaped
  provenance entry instead of leaving a dangling pull entry.

#493 part 3 — prune/supersede event shape in the provenance gate
  The gate accepts a removal event (empty outputs + non-empty removed
  list) and stops flagging a superseded path as missing, WITHOUT
  weakening the gate for normal entries (empty outputs on a NORMAL
  entry still FAILs). Malformed removals are caught.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
_PLUGIN_ROOT = _PROGRAMS.parent

import ip_catalog_query as cat              # noqa: E402
import ip_catalog_pull as pull             # noqa: E402
from ip_catalog_query import CatalogMatch  # noqa: E402
from provenance_output_hash_completeness_check import audit  # noqa: E402


# ===========================================================================
# #492 — synth_safe_params hint
# ===========================================================================
def _serv_manifest():
    mans = cat.load_manifests(_PLUGIN_ROOT / "ip-catalog")
    serv = [m for m in mans if m.get("ip_name") == "serv"]
    assert serv, "serv manifest must exist in catalog"
    return serv[0]


def test_492a_schema_documents_synth_safe_params():
    sch = json.loads(
        (_PLUGIN_ROOT / "ip-catalog" / "_schema"
         / "ip_manifest.schema.json").read_text())
    assert "synth_safe_params" in sch["properties"]
    item = sch["properties"]["synth_safe_params"]["items"]
    assert set(item["required"]) == {"param", "synth_safe_value", "reason"}
    # schema text explains the canonical PLI/system-task case
    blob = json.dumps(sch["properties"]["synth_safe_params"])
    assert "$value$plusargs" in blob or "PLI" in blob


def test_492a_serv_manifest_declares_sim_hint():
    serv = _serv_manifest()
    ssp = serv.get("synth_safe_params")
    assert isinstance(ssp, list) and ssp, "serv must declare synth_safe_params"
    sim = [e for e in ssp if e.get("param") == "sim"]
    assert sim, "serv synth_safe_params must pin the 'sim' param"
    entry = sim[0]
    assert entry["synth_safe_value"] == 0
    assert "reason" in entry and entry["reason"].strip()
    # sim param is also declared in the interface parameters
    params = [p.get("name") for p in serv["interface"]["parameters"]
              if isinstance(p, dict)]
    assert "sim" in params


def test_492_catalog_match_exposes_synth_overrides():
    serv = _serv_manifest()
    m = cat._manifest_to_match(serv, "pat", 0.9)
    assert isinstance(m.synth_safe_params, list) and m.synth_safe_params
    # The glue-author dry-run / source pin: {param: synth_safe_value}
    assert m.synth_param_overrides() == {"sim": 0}


def test_492_synth_param_overrides_skips_malformed_entries():
    m = CatalogMatch(
        ip_name="x", category="cpu", version="1.0", license="MIT",
        canonical_url="", canonical_commit="", matched_pattern="p",
        confidence=0.9, manifest_path="m",
        synth_safe_params=[
            {"param": "sim", "synth_safe_value": 0, "reason": "r"},
            {"param": "", "synth_safe_value": 1, "reason": "r"},   # no name
            {"synth_safe_value": 2, "reason": "r"},                # no param
            {"param": "noval", "reason": "r"},                     # no value
            "not-a-dict",
        ],
    )
    assert m.synth_param_overrides() == {"sim": 0}


def test_492b_integration_guide_states_sim_zero():
    guide = (_PLUGIN_ROOT / "ip-catalog" / "cpu" / "serv"
             / "integration_guide.md").read_text()
    assert "Synthesis-safety: pin `sim = 0`" in guide
    assert ".sim(1'b0)" in guide
    # explains WHY (unsynthesizable PLI / system tasks)
    assert "$value$plusargs" in guide and "yosys" in guide


def test_492c_skill_documents_synth_safe_params():
    skill = (_PLUGIN_ROOT / "skills" / "catalog-glue-author"
             / "SKILL.md").read_text()
    assert "Synthesis-safe parameters (`synth_safe_params`)" in skill
    # canonical sim-only generate block with PLI/system tasks
    assert "$value$plusargs" in skill
    assert "apply" in skill.lower() and "default" in skill.lower()


# ===========================================================================
# #493 part 1 — MANDATORY-vs-OPTIONAL extension matcher (unit level)
# ===========================================================================
def _facts_from_l2(project: Path, l2: dict):
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L2_FRS.json").write_text(json.dumps(l2))
    return cat.load_project_facts(project)


def test_493p1_optional_qualifier_suppresses(tmp_path):
    facts = _facts_from_l2(
        tmp_path / "p", {"cpu_isa": "rv32imc",
                         "cpu_extensions": "M, C; F (optional)"})
    ok, _ = cat._evaluate_match_rule(
        "L2.cpu_extensions contains 'F'", facts)
    assert ok is False


def test_493p1_optional_extensions_field_suppresses(tmp_path):
    facts = _facts_from_l2(
        tmp_path / "p", {"cpu_isa": "rv32i",
                         "isa_extensions_optional": "c, m, F"})
    ok, _ = cat._evaluate_match_rule(
        "L2.cpu_extensions contains 'F'", facts)
    assert ok is False


def test_493p1_base_isa_mandatory_still_matches(tmp_path):
    facts = _facts_from_l2(
        tmp_path / "p", {"cpu_isa": "rv32imf", "cpu_extensions": "M, F"})
    ok, conf = cat._evaluate_match_rule(
        "L2.cpu_extensions contains 'F'", facts)
    assert ok and conf == pytest.approx(0.9)


def test_493p1_plain_list_no_qualifier_matches(tmp_path):
    facts = _facts_from_l2(tmp_path / "p", {"cpu_extensions": "M, F, D"})
    ok, conf = cat._evaluate_match_rule(
        "L2.cpu_extensions contains 'F'", facts)
    assert ok and conf == pytest.approx(0.9)


def test_493p1_required_field_matches(tmp_path):
    facts = _facts_from_l2(
        tmp_path / "p", {"cpu_isa": "rv32i", "isa_extensions_mandatory": "F"})
    ok, _ = cat._evaluate_match_rule(
        "L2.cpu_extensions contains 'F'", facts)
    assert ok is True


def test_493p1_optional_only_unit_helper(tmp_path):
    # base-ISA mandatory overrides any optional phrase elsewhere
    assert cat._extension_optional_only(
        "F", "rv32imf", "rv32imf optional later", "") is False
    # pure optional mention
    assert cat._extension_optional_only(
        "F", "F (optional)", "F (optional)", "") is True
    # required field overrides
    assert cat._extension_optional_only(
        "F", "isa_extensions_mandatory: F", "", "") is False


# ===========================================================================
# #493 part 1 — END-TO-END via the real catalog (FPU mis-fire reproduction)
# ===========================================================================
def _mk_cpu_project(root: Path, l2: dict) -> Path:
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L2_FRS.json").write_text(json.dumps(l2))
    return root


def test_493p1_e2e_optional_f_does_not_match_fpu(tmp_path):
    """An rv32 CPU spec that mentions F only as OPTIONAL no longer pulls
    the FPU from the real catalog."""
    proj = _mk_cpu_project(
        tmp_path / "opt",
        {"cpu_isa": "rv32imc", "cpu_arch": "bit-serial",
         "cpu_family": "risc-v",
         "cpu_extensions": "M, C; F (optional, not implemented)"})
    matches = cat.query_catalog(
        proj, catalog_dir=_PLUGIN_ROOT / "ip-catalog", min_confidence=0.4)
    names = [m.ip_name for m in matches]
    assert "fpu_single" not in names


def test_493p1_e2e_mandatory_f_still_matches_fpu(tmp_path):
    """A genuine rv32...F ISA still matches the FPU."""
    proj = _mk_cpu_project(
        tmp_path / "man",
        {"cpu_isa": "rv32imf", "cpu_family": "risc-v",
         "cpu_extensions": "M, F"})
    matches = cat.query_catalog(
        proj, catalog_dir=_PLUGIN_ROOT / "ip-catalog", min_confidence=0.4)
    names = [m.ip_name for m in matches]
    assert "fpu_single" in names


# ===========================================================================
# #493 part 2 + 3 — prune path + gate event shape (end-to-end)
# ===========================================================================
def _mk_mirror(tmp_path: Path, n: int) -> Path:
    root = tmp_path / "mirror_root"
    ip = root / "demoip"
    for i in range(n):
        p = ip / "rtl" / f"file{i}.v"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"// file{i}\nmodule m{i}; endmodule\n")
    (ip / "LICENSE").write_text("MIT License — permissive\n")
    return root


def _demo_match(n: int) -> CatalogMatch:
    return CatalogMatch(
        ip_name="demoip", category="cpu", version="1.0", license="MIT",
        canonical_url="", canonical_commit="", matched_pattern="pat",
        confidence=0.9, manifest_path="m",
        rtl_files=[f"rtl/file{i}.v" for i in range(n)])


def test_493_e2e_pull6_prune6_gate_passes(tmp_path, monkeypatch):
    """The narrative: pull entry with 6 outputs → prune 6 files via the
    new path → provenance gate PASSes with the prune event. The OLD
    failure modes are reproduced first, then gone."""
    root = _mk_mirror(tmp_path, 6)
    monkeypatch.setattr(pull, "LOCAL_MIRROR_ROOTS", [root])
    monkeypatch.setattr(pull, "LOCAL_MIRROR_MAP", {})
    project = tmp_path / "proj"
    project.mkdir()

    # pull 6
    a = pull.pull_catalog_ip(_demo_match(6), project)
    assert a["status"] == "PASS" and a["n_files_copied"] == 6
    v, f = audit(project)
    assert v == "PASS", [(x.rule, x.detail) for x in f]

    # OLD failure mode: delete the files WITHOUT a prune -> missing-file
    for i in range(6):
        (project / "phase2" / "stage1" / "rtl" / f"file{i}.v").unlink()
    v_old, f_old = audit(project)
    assert v_old == "FAIL"
    assert any(x.rule == "PROVENANCE_OUTPUT_FILE_MISSING" for x in f_old)

    # Rebuild clean, then use the NEW prune path.
    shutil.rmtree(project)
    project.mkdir()
    pull.pull_catalog_ip(_demo_match(6), project)
    pr = pull.prune_catalog_ip(
        project, "demoip", reason="superseded", superseded_by="demoip_v2")
    assert pr["status"] == "PASS" and pr["n_removed"] == 6
    # The files are gone
    for i in range(6):
        assert not (project / "phase2" / "stage1" / "rtl" / f"file{i}.v").exists()

    # Gate PASSes WITH the prune event (no dangling missing-file fault).
    v2, f2 = audit(project)
    assert v2 == "PASS", [(x.rule, x.detail) for x in f2]

    # The provenance carries both the pull and the prune (removal) event.
    lines = [json.loads(l) for l in
             (project / "provenance.jsonl").read_text().splitlines() if l.strip()]
    events = [e.get("event") for e in lines]
    assert "ip_catalog_pull" in events and "ip_catalog_prune" in events
    prune_e = [e for e in lines if e.get("event") == "ip_catalog_prune"][0]
    assert prune_e["outputs"] == {}
    assert len(prune_e["removed"]) == 6


def test_493_prune_cli_smoke(tmp_path, monkeypatch):
    root = _mk_mirror(tmp_path, 3)
    monkeypatch.setattr(pull, "LOCAL_MIRROR_ROOTS", [root])
    monkeypatch.setattr(pull, "LOCAL_MIRROR_MAP", {})
    project = tmp_path / "proj"
    project.mkdir()
    pull.pull_catalog_ip(_demo_match(3), project)
    rc = pull.main([str(project), "--prune", "demoip",
                    "--reason", "obsolete", "--superseded-by", "newer"])
    assert rc == 0
    v, f = audit(project)
    assert v == "PASS", [(x.rule, x.detail) for x in f]


def test_493_prune_nonexistent_ip_fails(tmp_path, monkeypatch):
    root = _mk_mirror(tmp_path, 1)
    monkeypatch.setattr(pull, "LOCAL_MIRROR_ROOTS", [root])
    monkeypatch.setattr(pull, "LOCAL_MIRROR_MAP", {})
    project = tmp_path / "proj"
    project.mkdir()
    (project / "provenance.jsonl").write_text("")  # empty, no pull entry
    audit_dict = pull.prune_catalog_ip(project, "ghost")
    assert audit_dict["status"] == "FAIL"
    assert "nothing to prune" in audit_dict["reason"]


# --- gate-level guards (no weakening; malformed removals caught) -----------
def _mkprov(tmp_path: Path, entries: list) -> Path:
    d = tmp_path / "p"
    d.mkdir()
    (d / "provenance.jsonl").write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n")
    return d


def test_493p3_normal_empty_outputs_still_fails(tmp_path):
    d = _mkprov(tmp_path, [{"tool": "yosys", "outputs": {}}])
    v, f = audit(d)
    assert v == "FAIL"
    assert any(x.rule == "PROVENANCE_OUTPUTS_MISSING" for x in f)


def test_493p3_normal_missing_outputs_key_still_fails(tmp_path):
    d = _mkprov(tmp_path, [{"tool": "yosys", "command": "synth"}])
    v, f = audit(d)
    assert v == "FAIL"
    assert any(x.rule == "PROVENANCE_OUTPUTS_MISSING" for x in f)


def test_493p3_removal_event_accepted(tmp_path):
    d = _mkprov(tmp_path, [
        {"event": "ip_catalog_prune", "op": "remove",
         "outputs": {}, "removed": ["phase2/stage1/rtl/x.v"]}])
    v, f = audit(d)
    assert v == "PASS", [(x.rule, x.detail) for x in f]


def test_493p3_removal_empty_list_fails(tmp_path):
    d = _mkprov(tmp_path, [
        {"event": "ip_catalog_prune", "op": "remove",
         "outputs": {}, "removed": []}])
    v, f = audit(d)
    assert v == "FAIL"
    assert any(x.rule == "PROVENANCE_REMOVAL_EMPTY" for x in f)


def test_493p3_removal_file_still_present_fails(tmp_path):
    d = tmp_path / "p"
    (d / "phase2").mkdir(parents=True)
    (d / "phase2" / "x.v").write_text("still here")
    (d / "provenance.jsonl").write_text(json.dumps({
        "event": "ip_catalog_prune", "op": "remove",
        "outputs": {}, "removed": ["phase2/x.v"]}) + "\n")
    v, f = audit(d)
    assert v == "FAIL"
    assert any(x.rule == "PROVENANCE_REMOVAL_FILE_STILL_PRESENT" for x in f)


def test_493p3_removal_path_outside_project_fails(tmp_path):
    d = _mkprov(tmp_path, [
        {"event": "prune", "op": "remove",
         "outputs": {}, "removed": ["../../etc/passwd"]}])
    v, f = audit(d)
    assert v == "FAIL"
    assert any(x.rule == "PROVENANCE_PATH_OUTSIDE_PROJECT" for x in f)


def test_493p3_pull_then_prune_supersedes_missing_path(tmp_path):
    """A pull entry whose output was later removed by a prune event is
    NOT flagged missing (the removal supersedes it)."""
    d = tmp_path / "p"
    d.mkdir()
    (d / "provenance.jsonl").write_text(
        json.dumps({"event": "ip_catalog_pull", "ip": "z",
                    "outputs": {"phase2/stage1/rtl/g.v": "sha256:" + "a"*64}})
        + "\n"
        + json.dumps({"event": "ip_catalog_prune", "op": "remove",
                      "ip": "z", "outputs": {},
                      "removed": ["phase2/stage1/rtl/g.v"]})
        + "\n")
    v, f = audit(d)
    assert v == "PASS", [(x.rule, x.detail) for x in f]


def test_493p3_normal_missing_path_not_superseded_still_fails(tmp_path):
    """Without a prune event, a pull entry's missing output still FAILs."""
    d = tmp_path / "p"
    d.mkdir()
    (d / "provenance.jsonl").write_text(
        json.dumps({"event": "ip_catalog_pull", "ip": "z",
                    "outputs": {"phase2/stage1/rtl/g.v": "sha256:" + "a"*64}})
        + "\n")
    v, f = audit(d)
    assert v == "FAIL"
    assert any(x.rule == "PROVENANCE_OUTPUT_FILE_MISSING" for x in f)
