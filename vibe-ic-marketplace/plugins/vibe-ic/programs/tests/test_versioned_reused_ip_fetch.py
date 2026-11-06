"""Step 1 fetches only a named, pinned component and records its bytes."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

from _hostpaths import require_repo
from ip_catalog_query import CatalogMatch, query_catalog


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _upstream(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "reusable"
    (repo / "rtl").mkdir(parents=True)
    (repo / "rtl/leaf.v").write_text("module leaf; wire fixed = 1'b0; endmodule\n")
    (repo / "soc_top.v").write_text("module soc_top; endmodule\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "tagged core")
    _git(repo, "tag", "2.3.4")
    (repo / "rtl/leaf.v").write_text("module leaf; wire fixed = 1'b1; endmodule\n")
    _git(repo, "add", "rtl/leaf.v")
    _git(repo, "commit", "-qm", "upstream erratum")
    return repo, _git(repo, "rev-parse", "HEAD")


def _match(repo: Path, erratum: str, *, self_match: bool = False) -> CatalogMatch:
    fields = dict(
        ip_name="leaf", category="cpu", version="2.3.4", license="MIT",
        canonical_url=str(repo), canonical_commit="2.3.4",
        matched_pattern="L2.cpu_isa", confidence=0.9, manifest_path="synthetic",
        rtl_files=["rtl/leaf.v"], self_match=self_match,
    )
    if "errata" in CatalogMatch.__dataclass_fields__:
        fields["errata"] = [{"upstream_commit": erratum, "file": "rtl/leaf.v",
                             "disclosure": "upstream correction"}]
    return CatalogMatch(**fields)


def _project(tmp_path: Path, text: str) -> Path:
    project = tmp_path / "fabric"
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"part_name": "fabric"}))
    (docs / "L2_FRS.json").write_text(json.dumps({
        "cpu_isa": "rv32i", "cpu_arch": "bit-serial", "notes": text}))
    return project


def test_step1_fetches_exact_upstream_core_and_discloses_erratum(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import design_one_shot_runner as runner
    import ip_catalog_query as query

    repo, erratum = _upstream(tmp_path)
    match = _match(repo, erratum)
    monkeypatch.setattr(query, "query_catalog", lambda *a, **k: [match])
    project = _project(tmp_path, "Reuse leaf from vendor:reusable:leaf:2.3.4.")

    result = runner.step_rtl_gen(project, "processor_cpu")
    assert result.status == "PASS_WITH_WAIVERS"
    assert "Fetched declared versioned reused IP ['leaf']" in result.detail
    assert result.extras["ip_fetch"]["n_ips_pulled"] == 1
    rtl = project / "phase2/stage1/rtl"
    assert (rtl / "leaf.v").read_text() == "module leaf; wire fixed = 1'b1; endmodule\n"
    assert not (rtl / "soc_top.v").exists()
    manifest = json.loads((rtl / "SOURCE_MANIFEST.json").read_text())
    pin = manifest["source_pins"][0]
    assert pin["version"] == "2.3.4"
    assert pin["checked_out_sha"] == _git(repo, "rev-parse", "2.3.4")
    assert pin["files_sha256"]["rtl/leaf.v"] == hashlib.sha256(
        (rtl / "leaf.v").read_bytes()).hexdigest()
    assert pin["errata_applied"][0]["upstream_commit"] == erratum
    provenance = [json.loads(line) for line in (project / "provenance.jsonl").read_text().splitlines()]
    pulls = [row for row in provenance if row.get("event") == "ip_catalog_pull"]
    assert len(pulls) == 1
    assert pulls[0]["errata_applied"][0]["upstream_commit"] == erratum
    assert pulls[0]["outputs"]["phase2/stage1/rtl/leaf.v"] == (
        "sha256:" + pin["files_sha256"]["rtl/leaf.v"])

    again = runner.step_rtl_gen(project, "processor_cpu")
    assert again.extras["ip_fetch"]["status"] == "ALREADY_FETCHED"
    assert len([row for row in (project / "provenance.jsonl").read_text().splitlines()
                if json.loads(row).get("event") == "ip_catalog_pull"]) == 1


def test_existing_pin_cannot_attest_arbitrary_rtl_without_official_pull(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import design_one_shot_runner as runner
    import ip_catalog_query as query

    repo, erratum = _upstream(tmp_path)
    match = _match(repo, erratum)
    monkeypatch.setattr(query, "query_catalog", lambda *a, **k: [match])
    project = _project(tmp_path, "Reuse leaf from vendor:reusable:leaf:2.3.4.")
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    arbitrary = b"module leaf; wire fixed = 1'bx; endmodule\n"
    (rtl / "leaf.v").write_bytes(arbitrary)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps({
        "reused_ip": True,
        "source_pins": [{
            "ip_name": "leaf", "version": match.version,
            "canonical_url": match.canonical_url,
            "files_sha256": {"rtl/leaf.v": hashlib.sha256(arbitrary).hexdigest()},
        }],
    }))

    result = runner.step_rtl_gen(project, "processor_cpu")
    assert result.status == "FAIL"
    assert "IP_REUSE_FETCH_PIN_MISMATCH" in result.detail
    assert (rtl / "leaf.v").read_bytes() == arbitrary


def test_complete_receipts_cannot_launder_changed_rtl(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import design_one_shot_runner as runner
    import ip_catalog_query as query

    repo, erratum = _upstream(tmp_path)
    match = _match(repo, erratum)
    monkeypatch.setattr(query, "query_catalog", lambda *a, **k: [match])
    project = _project(tmp_path, "Reuse leaf from vendor:reusable:leaf:2.3.4.")
    assert runner.step_rtl_gen(project, "processor_cpu").status == "PASS_WITH_WAIVERS"

    rtl = project / "phase2/stage1/rtl"
    arbitrary = b"module leaf; wire fixed = 1'bx; endmodule\n"
    (rtl / "leaf.v").write_bytes(arbitrary)
    digest = hashlib.sha256(arbitrary).hexdigest()
    mf_path = rtl / "SOURCE_MANIFEST.json"
    manifest = json.loads(mf_path.read_text())
    manifest["source_pins"][0]["files_sha256"]["rtl/leaf.v"] = digest
    mf_path.write_text(json.dumps(manifest))
    prov_path = project / "provenance.jsonl"
    events = [json.loads(line) for line in prov_path.read_text().splitlines()]
    events[-1]["outputs"]["phase2/stage1/rtl/leaf.v"] = "sha256:" + digest
    events[-1]["outputs_sha256"] = [digest]
    prov_path.write_text("\n".join(json.dumps(event) for event in events) + "\n")

    result = runner.step_rtl_gen(project, "processor_cpu")
    assert result.status == "FAIL"
    assert "IP_REUSE_FETCH_PIN_MISMATCH" in result.detail
    assert (rtl / "leaf.v").read_bytes() == arbitrary


@pytest.mark.parametrize("missing", ["event", "errata", "commit"])
def test_existing_pin_requires_complete_official_receipt(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    import design_one_shot_runner as runner
    import ip_catalog_query as query

    repo, erratum = _upstream(tmp_path)
    monkeypatch.setattr(query, "query_catalog",
                        lambda *a, **k: [_match(repo, erratum)])
    project = _project(tmp_path, "Reuse leaf from vendor:reusable:leaf:2.3.4.")
    assert runner.step_rtl_gen(project, "processor_cpu").status == "PASS_WITH_WAIVERS"
    manifest_path = project / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
    if missing == "event":
        (project / "provenance.jsonl").unlink()
    else:
        manifest = json.loads(manifest_path.read_text())
        pin = manifest["source_pins"][0]
        if missing == "errata":
            pin["errata_applied"] = []
        else:
            pin.pop("checked_out_sha")
        manifest_path.write_text(json.dumps(manifest))

    result = runner.step_rtl_gen(project, "processor_cpu")
    assert result.status == "FAIL"
    assert "IP_REUSE_FETCH_PIN_MISMATCH" in result.detail


@pytest.mark.parametrize("text,reason", [
    ("A generic bit-serial CPU. vendor:reusable:core:2.3.4.",
     "IP_REUSE_NAME_UNDECLARED: leaf"),
    ("Reuse leaf from the reusable repository.",
     "IP_REUSE_SOURCE_OR_VERSION_UNDECLARED: leaf"),
    ("Do not reuse leaf from vendor:reusable:leaf:2.3.4.",
     "IP_REUSE_DECLARATION_DENIED: leaf"),
])
def test_unnamed_or_unversioned_match_is_refused_by_name(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        text: str, reason: str) -> None:
    import design_one_shot_runner as runner
    import ip_catalog_query as query
    repo, erratum = _upstream(tmp_path)
    monkeypatch.setattr(query, "query_catalog", lambda *a, **k: [_match(repo, erratum)])
    project = _project(tmp_path, text)
    result = runner.step_rtl_gen(project, "processor_cpu")
    assert result.status == "PASS_WITH_WAIVERS"
    assert result.extras["ip_fetch_refusals"] == [reason]
    assert not (project / "phase2/stage1/rtl/leaf.v").exists()


def test_design_under_test_is_still_refused(tmp_path: Path) -> None:
    repo, erratum = _upstream(tmp_path)
    match = _match(repo, erratum, self_match=True)
    match.self_match_reason = "catalog entry supplies the IC-under-test's OWN design"
    project = _project(tmp_path, "Reuse leaf from vendor:reusable:leaf:2.3.4.")
    assert not (project / "phase2/stage1/rtl/leaf.v").exists()


def test_real_catalog_component_has_versioned_source_and_scoped_erratum(
        tmp_path: Path) -> None:
    """Read the checked-in catalog artefact through its real query consumer."""
    manifest = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                            "ip-catalog", "cpu", "serv", "manifest.yaml")
    project = _project(tmp_path, "Reuse servile CPU from award-winning:serv:servile:1.4.0.")
    docs = project / "input/docs"
    docs.mkdir(parents=True)
    (docs / "L8_integration.md").write_text(
        "sources: reference_serv/doc/interface.rst\n"
        "Reuse the SERV core via award-winning:serv:servile:1.4.0.\n")
    matches = query_catalog(project, catalog_dir=manifest.parent.parent.parent,
                            ic_name="fabric")
    assert [(m.ip_name, m.self_match, m.version) for m in matches] == [
        ("serv", False, "1.4.0")]
    assert {e["file"] for e in matches[0].errata} == {
        "servile/servile_rf_mem_if.v", "rtl/serv_state.v"}
    assert all(e["file"] in matches[0].rtl_files for e in matches[0].errata)


def test_an_unreachable_reference_pull_is_not_measured_not_a_mismatch(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MEASURED on a subservient DIE front door (2026-09-29): the independent
    re-pull of the pinned core timed out (`git clone` 153 s against a 120 s
    budget) and Step 1 reported IP_REUSE_FETCH_PIN_MISMATCH, "bytes differ",
    about bytes nobody compared. Unverifiable pins are still refused, but as
    NOT_MEASURED with the fetch reason; a real mismatch stays FAIL (the tests
    above)."""
    import design_one_shot_runner as runner
    import ip_catalog_query as query

    repo, erratum = _upstream(tmp_path)
    match = _match(repo, erratum)
    monkeypatch.setattr(query, "query_catalog", lambda *a, **k: [match])
    project = _project(tmp_path, "Reuse leaf from vendor:reusable:leaf:2.3.4.")
    first = runner.step_rtl_gen(project, "processor_cpu")
    assert first.status == "PASS_WITH_WAIVERS"
    repo.rename(tmp_path / "unreachable")        # the upstream stops answering

    result = runner.step_rtl_gen(project, "processor_cpu")
    assert result.status == "NOT_MEASURED", result.detail
    assert "IP_REUSE_PIN_VERIFY_UNAVAILABLE" in result.detail
    assert "IP_REUSE_FETCH_PIN_MISMATCH" not in result.detail
    assert str(repo) in result.detail            # the fetch reason is named


# ── review wave 58 (U8FETCH): UNAVAILABLE is a fetch that never reached a
# tree, and only when every comparison that COULD be made agreed. Each case
# below was MEASURED as a false NOT_MEASURED on d3f820987; each must FAIL. ──

def _first_pull(tmp_path, monkeypatch, matches, text):
    import design_one_shot_runner as runner
    import ip_catalog_query as query
    monkeypatch.setattr(query, "query_catalog", lambda *a, **k: list(matches))
    project = _project(tmp_path, text)
    first = runner.step_rtl_gen(project, "processor_cpu")
    assert first.status == "PASS_WITH_WAIVERS", first.detail
    return runner, project


def test_default_canonical_cache_honors_tmpdir(tmp_path):
    result=subprocess.run([sys.executable,'-c','from ip_catalog_pull import CACHE_ROOT; print(CACHE_ROOT)'],
        cwd=PROGRAMS,env={'TMPDIR':str(tmp_path),'VIBEIC_IP_SOURCE_CACHE':'','PYTHONDONTWRITEBYTECODE':'1'},
        check=True,capture_output=True,text=True)
    assert result.stdout.strip()==str(tmp_path/'vibe_ic_catalog_cache')


def _repoint_tag(repo: Path, *, drop_leaf: bool = False) -> None:
    """Upstream force-moves the release tag to a side commit off the old tag."""
    _git(repo, "checkout", "-q", "-b", "rewrite", "2.3.4")
    if drop_leaf:
        _git(repo, "rm", "-q", "rtl/leaf.v")
    else:
        (repo / "rtl/leaf.v").write_text("module leaf; wire fixed = 1'bz; endmodule\n")
        _git(repo, "add", "rtl/leaf.v")
    _git(repo, "commit", "-qm", "rewritten release")
    _git(repo, "tag", "-f", "2.3.4")
    _git(repo, "checkout", "-q", "-")


@pytest.mark.parametrize("drop_leaf,reason", [
    (False, "IP_REUSE_ERRATUM_BASE_MISMATCH"),
    (True, "IP_REUSE_RTL_MISSING"),
])
def test_a_rewritten_release_tag_with_an_erratum_is_a_mismatch(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drop_leaf, reason) -> None:
    """The real catalog entry pins a TAG and carries errata. A re-pointed tag
    is decided on the bytes the reference fetched, so it is a FAIL, exactly as
    the same rewrite with no erratum already is."""
    repo, erratum = _upstream(tmp_path)
    runner, project = _first_pull(tmp_path, monkeypatch, [_match(repo, erratum)],
                                  "Reuse leaf from vendor:reusable:leaf:2.3.4.")
    _repoint_tag(repo, drop_leaf=drop_leaf)
    result = runner.step_rtl_gen(project, "processor_cpu")
    assert result.status == "FAIL", result.detail
    assert "IP_REUSE_FETCH_PIN_MISMATCH" in result.detail
    assert reason in result.detail


def test_a_licence_refusal_of_the_reference_is_a_mismatch(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ip_catalog_query as query
    repo, erratum = _upstream(tmp_path)
    runner, project = _first_pull(tmp_path, monkeypatch, [_match(repo, erratum)],
                                  "Reuse leaf from vendor:reusable:leaf:2.3.4.")
    gpl = _match(repo, erratum)
    object.__setattr__(gpl, "license", "GPL-3.0-only") \
        if getattr(type(gpl), "__dataclass_params__", None) and \
        type(gpl).__dataclass_params__.frozen else setattr(gpl, "license", "GPL-3.0-only")
    monkeypatch.setattr(query, "query_catalog", lambda *a, **k: [gpl])
    result = runner.step_rtl_gen(project, "processor_cpu")
    assert result.status == "FAIL", result.detail
    assert "IP_REUSE_FETCH_PIN_MISMATCH" in result.detail


def test_own_receipts_disagreeing_is_a_mismatch_even_when_upstream_is_gone(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, erratum = _upstream(tmp_path)
    runner, project = _first_pull(tmp_path, monkeypatch, [_match(repo, erratum)],
                                  "Reuse leaf from vendor:reusable:leaf:2.3.4.")
    (project / "phase2/stage1/rtl/leaf.v").write_text("module leaf; endmodule\n")
    repo.rename(tmp_path / "unreachable")
    result = runner.step_rtl_gen(project, "processor_cpu")
    assert result.status == "FAIL", result.detail
    assert "own pin receipt" in result.detail


def _twig(tmp_path: Path) -> CatalogMatch:
    """A second declared IP from its own upstream clone."""
    twig_repo = tmp_path / "twigup"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "reusable"), str(twig_repo)],
                   check=True, capture_output=True)
    fields = dict(ip_name="twig", category="cpu", version="2.3.4", license="MIT",
                  canonical_url=str(twig_repo), canonical_commit="2.3.4",
                  matched_pattern="L2.cpu_isa", confidence=0.9,
                  manifest_path="synthetic", rtl_files=["soc_top.v"])
    if "errata" in CatalogMatch.__dataclass_fields__:
        fields["errata"] = []
    return CatalogMatch(**fields)


def test_an_unreachable_second_ip_cannot_hide_a_proven_mismatch_in_the_first(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, erratum = _upstream(tmp_path)
    twig = _twig(tmp_path)
    text = ("Reuse leaf from vendor:reusable:leaf:2.3.4. "
            "Reuse twig from vendor:twigup:twig:2.3.4.")
    runner, project = _first_pull(tmp_path, monkeypatch,
                                  [_match(repo, erratum), twig], text)
    # launder leaf with receipts that agree with the new bytes (the case
    # test_complete_receipts_cannot_launder_changed_rtl guards) ...
    rtl = project / "phase2/stage1/rtl"
    arbitrary = b"module leaf; wire fixed = 1'bx; endmodule\n"
    (rtl / "leaf.v").write_bytes(arbitrary)
    digest = hashlib.sha256(arbitrary).hexdigest()
    mf_path = rtl / "SOURCE_MANIFEST.json"
    manifest = json.loads(mf_path.read_text())
    for pin in manifest["source_pins"]:
        if pin["ip_name"] == "leaf":
            pin["files_sha256"]["rtl/leaf.v"] = digest
    mf_path.write_text(json.dumps(manifest))
    prov_path = project / "provenance.jsonl"
    events = [json.loads(line) for line in prov_path.read_text().splitlines()]
    for ev in events:
        if ev.get("ip") == "leaf":
            ev["outputs"]["phase2/stage1/rtl/leaf.v"] = "sha256:" + digest
            ev["outputs_sha256"] = [digest]
    prov_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    # ... and make ONLY twig's upstream unreachable
    Path(twig.canonical_url).rename(tmp_path / "twig_gone")
    result = runner.step_rtl_gen(project, "processor_cpu")
    assert result.status == "FAIL", result.detail
    assert "IP_REUSE_FETCH_PIN_MISMATCH" in result.detail


def test_control_two_ips_one_unreachable_and_all_else_agreeing_is_not_measured(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, erratum = _upstream(tmp_path)
    twig = _twig(tmp_path)
    text = ("Reuse leaf from vendor:reusable:leaf:2.3.4. "
            "Reuse twig from vendor:twigup:twig:2.3.4.")
    runner, project = _first_pull(tmp_path, monkeypatch,
                                  [_match(repo, erratum), twig], text)
    Path(twig.canonical_url).rename(tmp_path / "twig_gone")
    result = runner.step_rtl_gen(project, "processor_cpu")
    assert result.status == "NOT_MEASURED", result.detail
    assert "IP_REUSE_PIN_VERIFY_UNAVAILABLE" in result.detail
    assert "twig" in result.detail and "leaf:" not in result.detail
