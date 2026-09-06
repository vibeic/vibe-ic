"""RB2-02 (#2063) — the catalog self-match guard let the design's OWN ORIGIN
repo through, because it compared TOKENS and an origin's repo name need not
share a token with the design's name.

MEASURED on the subservient cell (lane rbsub2, 8HD-8, 2026-09-06): the guard
refused `shared_sram_rf` (shares the token `subservient`) and returned `serv`
at confidence 0.45 — whose `canonical_url` is `github.com/olofk/serv`, the very
upstream that cell's own input docs cite as `reference_serv/`. Pulling it would
hand the generation its own origin through the front door.

The fix adds a SECOND refusal on its own axis — the entry's upstream REPO
identity against the origin the INPUT docs state — and keeps the token arm as
the FIRST refusal. Both directions are asserted here: the origin is refused,
and an unrelated component IP is still returned from the very same query.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import ip_catalog_query as Q  # noqa: E402


def _match(ip_name, url):
    return Q.CatalogMatch(
        ip_name=ip_name, category="", version="0", license="MIT",
        canonical_url=url, canonical_commit="", matched_pattern="x",
        confidence=0.7, manifest_path="", rtl_files=[])


# ── unit: what counts as a STATED origin ────────────────────────────────

def test_origin_idents_read_the_reference_path_convention():
    facts = {"_full_text": "sources: reference_serv/doc/interface.rst and "
                           "reference/README.md"}
    assert Q._declared_origin_idents(facts) == {"serv"}


def test_a_component_the_docs_merely_mention_is_not_an_origin():
    facts = {"_full_text": "drive it with an off-the-shelf spi_master core; "
                           "see https://github.com/foo/spi_master"}
    assert Q._declared_origin_idents(facts) == set()


def test_no_docs_no_origin():
    assert Q._declared_origin_idents({}) == set()
    assert Q._declared_origin_idents({"_full_text": ""}) == set()


# ── unit: the refusal, both directions ──────────────────────────────────

def test_origin_repo_is_refused_even_with_no_shared_token():
    mt = _match("serv", "https://github.com/olofk/serv")
    # token arm sees nothing: 'serv' vs 'subservient' do not intersect
    assert Q._self_match_reason(mt, {}, {"subservient"}) == ""
    reason = Q._self_match_reason(mt, {}, {"subservient"}, {"serv"})
    assert reason
    assert "design origin" in reason


def test_unrelated_entry_is_not_refused_by_the_origin_arm():
    mt = _match("spi_master", "https://github.com/foo/spi_master")
    assert Q._self_match_reason(mt, {}, {"subservient"}, {"serv"}) == ""


def test_token_arm_still_fires_and_keeps_its_own_wording():
    mt = _match("shared_sram_rf", "https://github.com/foo/anything")
    mt.rtl_files = ["rtl/subservient.v"]
    reason = Q._self_match_reason(mt, {}, {"subservient"}, {"serv"})
    assert "#187" in reason


# ── end to end through query_catalog ────────────────────────────────────

def _build(tmp_path):
    cat = tmp_path / "ip-catalog"
    (cat / "_schema").mkdir(parents=True)
    org = cat / "cpu" / "serv"
    org.mkdir(parents=True)
    (org / "manifest.yaml").write_text(
        "ip_name: serv\nip_version: \"1.4.0\"\nlicense: ISC\n"
        "canonical_url: https://github.com/olofk/serv\n"
        "rtl_files:\n  - rtl/serv_top.v\n"
        "matches_when:\n  - \"L2 contains 'bit-serial'\"\n")
    comp = cat / "peripheral" / "widgetuart"
    comp.mkdir(parents=True)
    (comp / "manifest.yaml").write_text(
        "ip_name: widgetuart\nip_version: \"1.0.0\"\nlicense: MIT\n"
        "canonical_url: https://github.com/foo/widgetuart\n"
        "rtl_files:\n  - rtl/widgetuart.v\n"
        "matches_when:\n  - \"L2 contains 'needuart'\"\n")
    proj = tmp_path / "subservient"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"part_name": "subservient"}))
    (gd / "L2_FRS.json").write_text(json.dumps(
        {"notes": "a bit-serial cpu that also needuart. "
                  "source: reference_serv/doc/interface.rst"}))
    return cat, proj


def test_query_refuses_the_origin_and_keeps_the_component(tmp_path):
    cat, proj = _build(tmp_path)
    names = {m.ip_name for m in
             Q.query_catalog(proj, catalog_dir=cat, min_confidence=0.4)}
    assert "serv" not in names          # the design's OWN origin, refused
    assert "widgetuart" in names        # an unrelated component IP, kept


def test_without_the_origin_citation_the_same_entry_is_returned(tmp_path):
    """The negative control for the guard itself: the refusal must come from
    the DOCS' origin statement and from nothing else. Same catalog, same
    predicates, one sentence removed."""
    cat, proj = _build(tmp_path)
    gd = proj / "phase1" / "generated_docs"
    (gd / "L2_FRS.json").write_text(json.dumps(
        {"notes": "a bit-serial cpu that also needuart."}))
    names = {m.ip_name for m in
             Q.query_catalog(proj, catalog_dir=cat, min_confidence=0.4)}
    assert names == {"serv", "widgetuart"}
