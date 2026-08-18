"""v1.4.73 — #187 (BENCHMARK INTEGRITY): ip_catalog offered the IC-under-test's
OWN upstream reference design as a high-confidence catalog match — handing the
generation the answer key through the front door (§4.05 forbids reading the
oracle; the catalog can hand it over just the same).

Fix (chip-AGNOSTIC): a SELF-MATCH GUARD in ip_catalog_query / ip_catalog_pull.
A catalog entry whose module set / upstream repo intersects the IC's TOP-LEVEL
identity (its ic-name / L1 part identity / top_module) SUPPLIES the IC's own
design and is REFUSED by default; a legitimate leaf COMPONENT IP (whose tokens
never touch the IC's own top) is unaffected. `allow_self_match=True` returns
such entries flagged for an explicit-acknowledgement caller. pull_catalog_ip
REJECTS a flagged self-match as defense-in-depth.

chip-AGNOSTIC: pure name/repo normalization; no chip/vendor/SKU literal.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import ip_catalog_query as Q  # noqa: E402
import ip_catalog_pull as P  # noqa: E402


# ════════════════════════════════════════════════════════════════════════
# unit — the identity + self-match predicates
# ════════════════════════════════════════════════════════════════════════

def test_norm_ident_strips_path_ext_and_url():
    assert Q._norm_ident("rtl/widgetsoc.v") == "widgetsoc"
    assert Q._norm_ident("https://github.com/foo/widgetsoc.git") == "widgetsoc"
    assert Q._norm_ident("WidgetSoc") == "widgetsoc"
    assert Q._norm_ident("") == ""


def _match(ip_name, rtl, url=""):
    return Q.CatalogMatch(
        ip_name=ip_name, category="", version="0", license="MIT",
        canonical_url=url, canonical_commit="", matched_pattern="x",
        confidence=0.7, manifest_path="", rtl_files=rtl)


def test_self_match_reason_fires_on_ic_top():
    ic = {"widgetsoc"}
    mt = _match("shared_thing",
                ["rtl/widgetsoc.v", "rtl/widgetsoc_core.v"],
                "https://github.com/foo/widgetsoc")
    assert Q._self_match_reason(mt, {}, ic) != ""


def test_self_match_reason_empty_for_leaf_component():
    ic = {"widgetsoc"}
    mt = _match("serv", ["rtl/serv_top.v", "rtl/serv_alu.v"],
                "https://github.com/olofk/serv")
    assert Q._self_match_reason(mt, {}, ic) == ""


def test_generic_top_module_dropped_from_identity(tmp_path):
    # The runner's generic wrapper name `chip_top` must be dropped from the IC
    # identity, so a catalog SoC entry that also declares a `chip_top` module is
    # NOT a false self-match (else every SoC entry would be refused).
    assert "chip_top" in Q._GENERIC_IDENT_STOP
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L3_INTERFACE.json").write_text(json.dumps({"top_module": "chip_top"}))
    ident = Q._ic_identity_tokens(tmp_path, Q.load_project_facts(tmp_path))
    assert "chip_top" not in ident
    mt = _match("some_soc", ["rtl/chip_top.v"], "")
    assert Q._self_match_reason(mt, {}, ident) == ""


# ════════════════════════════════════════════════════════════════════════
# integration — query_catalog refuses the self-match, keeps the component
# ════════════════════════════════════════════════════════════════════════

def _build_catalog(root: Path) -> Path:
    cat = root / "ip-catalog"
    (cat / "_schema").mkdir(parents=True)
    comp = cat / "cpu" / "tinyriscv"
    comp.mkdir(parents=True)
    (comp / "manifest.yaml").write_text(
        "ip_name: tinyriscv\nip_version: \"1.0.0\"\nlicense: MIT\n"
        "canonical_url: https://github.com/foo/tinyriscv\n"
        "rtl_files:\n  - rtl/tinyriscv.v\n  - rtl/tinyriscv_alu.v\n"
        "matches_when:\n  - \"L2 contains 'needcpu'\"\n")
    selfm = cat / "memory" / "shared_thing"
    selfm.mkdir(parents=True)
    (selfm / "manifest.yaml").write_text(
        "ip_name: shared_thing\nip_version: \"0.2.2\"\nlicense: Apache-2.0\n"
        "canonical_url: https://github.com/foo/widgetsoc\n"
        "rtl_files:\n  - rtl/widgetsoc.v\n  - rtl/widgetsoc_core.v\n"
        "  - rtl/widgetsoc_gpio.v\n"
        "matches_when:\n  - \"L2 contains 'needsram'\"\n")
    return cat


def _build_project(root: Path) -> Path:
    proj = root / "widgetsoc"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"part_name": "widgetsoc"}))
    (gd / "L2_FRS.json").write_text(json.dumps(
        {"notes": "needcpu and needsram in this soc"}))
    (gd / "L3_INTERFACE.json").write_text(json.dumps({"top_module": "widgetsoc"}))
    return proj


def test_query_refuses_self_match_keeps_component(tmp_path):
    cat = _build_catalog(tmp_path)
    proj = _build_project(tmp_path)
    res = Q.query_catalog(proj, catalog_dir=cat, min_confidence=0.4)
    names = {m.ip_name for m in res}
    assert "tinyriscv" in names          # legit component IP kept
    assert "shared_thing" not in names   # IC's own design REFUSED


def test_query_allow_self_match_returns_flagged(tmp_path):
    cat = _build_catalog(tmp_path)
    proj = _build_project(tmp_path)
    res = Q.query_catalog(proj, catalog_dir=cat, min_confidence=0.4,
                          allow_self_match=True)
    by = {m.ip_name: m for m in res}
    assert by["shared_thing"].self_match is True
    assert by["shared_thing"].self_match_reason
    assert by["tinyriscv"].self_match is False


def test_query_explicit_ic_name_strengthens_guard(tmp_path):
    # Even when the project docs are sparse, an explicit ic-name refuses the
    # self-match.
    cat = _build_catalog(tmp_path)
    proj = tmp_path / "run_v99"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L2_FRS.json").write_text(json.dumps({"notes": "needsram needcpu"}))
    res = Q.query_catalog(proj, catalog_dir=cat, min_confidence=0.4,
                          ic_name="widgetsoc")
    assert "shared_thing" not in {m.ip_name for m in res}


# ════════════════════════════════════════════════════════════════════════
# defense-in-depth — pull refuses a flagged self-match
# ════════════════════════════════════════════════════════════════════════

def test_pull_rejects_flagged_self_match(tmp_path):
    mt = _match("shared_thing", ["rtl/widgetsoc.v"],
                "https://github.com/foo/widgetsoc")
    mt.self_match = True
    mt.self_match_reason = "supplies the IC's own design"
    audit = P.pull_catalog_ip(mt, tmp_path)
    assert audit["status"] == "REJECTED"
    assert "own design" in audit["reason"] or "#187" in audit["reason"]
