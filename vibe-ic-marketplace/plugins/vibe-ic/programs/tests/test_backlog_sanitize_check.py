#!/usr/bin/env python3
"""Tests for backlog_sanitize_check.py"""
from __future__ import annotations
import json
import subprocess, sys
import tempfile
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "backlog_sanitize_check.py"
REGISTRY = PROG.parent / "oss_core_registry.json"


def _shipped_version() -> str:
    """The manifest's version. Hard-coded before, which made this fixture red on
    every release bump for a reason nobody broke."""
    import json as _j
    here = Path(__file__).resolve().parent.parent.parent
    return str(_j.loads((here / ".claude-plugin" / "plugin.json").read_text())["version"])



def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_clean_yaml(tmp_path):
    bf = tmp_path / "backlog.yaml"
    bf.write_text("type: enhancement\ncomponent: skill:spec-to-rtl\ntitle: Add SPI timeout\npattern: SPI clock recovery should handle jitter\nplugin_version: '" + _shipped_version() + "'\n")
    r = _run(["--file", str(bf)])
    assert r.returncode == 0

def test_empty_dir(tmp_path):
    r = _run(["--dir", str(tmp_path)])
    assert r.returncode == 0


# --- `pattern` is a REQUIRED field of the record, downstream of emit -------

def test_required_fields_is_exactly_this_set():
    """Pinned as literals + set equality (never by iterating the constant
    under test). `pattern` sits in here — the downstream half of the
    asymmetry that `enhancement_emit.emit_backlog` left unenforced at the
    write site, where an omitted one emitted a plausible empty block."""
    sys.path.insert(0, str(PROG.parent))
    import backlog_sanitize_check as mod
    assert set(mod.REQUIRED_FIELDS) == {
        "type", "component", "title", "pattern", "plugin_version"}


def test_empty_pattern_is_flagged_missing(tmp_path):
    """Behavioural downstream half: the gate rejects the exact file an
    unenforced emit used to be able to write."""
    bf = tmp_path / "b.yaml"
    bf.write_text("type: enhancement\ncomponent: skill:spec-to-rtl\n"
                  "title: A gate accepts what it should refuse\n"
                  "pattern: |\n  \n"
                  "plugin_version: '" + _shipped_version() + "'\n")
    r = _run(["--file", str(bf)])
    assert r.returncode == 1
    cats = [(f["category"], f["field"])
            for f in json.loads(r.stdout)["findings"]]
    assert ("MISSING_FIELD", "pattern") in cats, cats


# --- OSS-core codename SOFT registry rule ---------------------------------

def test_registry_data_file_exists_and_wellformed():
    """The OSS-core registry is a maintained DATA file (not a regex literal)."""
    assert REGISTRY.exists(), "oss_core_registry.json must ship next to the program"
    data = json.loads(REGISTRY.read_text())
    cores = data.get("cores")
    assert isinstance(cores, list) and cores, "registry must hold a non-empty cores list"
    # The codenames the phase1-coverage-loop prose deny-list enumerates.
    for name in ("picorv32", "ibex", "cv32e40p", "neorv32", "serv", "VexRiscv", "darkriscv"):
        assert name in cores, f"{name} should be in the curated OSS-core registry"


def test_warn_oss_codename_in_title(tmp_path):
    """REAL DEFECT: a backlog whose generic-description TITLE names a specific
    OSS core ('serv') instead of the IC class -> WARN oss_core_codename.
    Must stay non-blocking (WARN, exit 0), never a hard ERROR."""
    bf = tmp_path / "b.yaml"
    bf.write_text(
        "type: enhancement\n"
        "component: program:flow_compliance_check\n"
        "title: serv core fails the submodule-instantiation structural gate\n"
        "pattern: a bit-serial RISC-V core's look-ahead shift is flagged as a race\n"
        "plugin_version: '" + _shipped_version() + "'\n"
    )
    r = _run(["--file", str(bf)])
    rep = json.loads(r.stdout)
    oss = [f for f in rep["findings"] if f["category"] == "oss_core_codename"]
    assert oss, "expected a WARN on the OSS codename in the title"
    assert oss[0]["severity"] == "WARN", "must be WARN, never a hard ERROR"
    assert oss[0]["field"] == "title"
    assert oss[0]["matched"].lower() == "serv"
    # WARN alone must NOT block (no ERROR-class finding => exit 0).
    assert not any(f["severity"] == "ERROR" for f in rep["findings"])
    assert r.returncode == 0


def test_no_warn_oss_codename_in_pattern_or_context(tmp_path):
    """SCOPING: the SAME codename in pattern / suggested_fix / session_context
    is LEGITIMATE provenance/corpus-naming and must NOT fire (mirrors the real
    bitserial-cpu and benchmark-ic-corpus backlogs)."""
    bf = tmp_path / "b.yaml"
    bf.write_text(
        "type: enhancement\n"
        "component: program:flow_compliance_check\n"
        "title: structural gate false-positives on a validated bit-serial RISC-V core\n"
        "pattern: catalog-glue-author pulls cpu/serv@1.4.0 and three gates emit FAIL\n"
        "suggested_fix: regenerate subservient then darkriscv then picorv32 in order\n"
        "session_context: fresh field-agent run on the serv RV32I core; neorv32 control\n"
        "plugin_version: '" + _shipped_version() + "'\n"
    )
    r = _run(["--file", str(bf)])
    rep = json.loads(r.stdout)
    oss = [f for f in rep["findings"] if f["category"] == "oss_core_codename"]
    assert not oss, (
        "codename in pattern/suggested_fix/session_context is legitimate "
        f"provenance and must NOT be flagged; got {oss}"
    )


def test_word_boundary_no_false_fire_on_substrings(tmp_path):
    """'serv' must not match inside 'subservient' / 'server' / 'service'."""
    bf = tmp_path / "b.yaml"
    bf.write_text(
        "type: enhancement\n"
        "component: program:phase3_runner\n"
        "title: subservient server service does not observe the reserved net\n"
        "pattern: a generic check\n"
        "plugin_version: '" + _shipped_version() + "'\n"
    )
    r = _run(["--file", str(bf)])
    rep = json.loads(r.stdout)
    oss = [f for f in rep["findings"] if f["category"] == "oss_core_codename"]
    assert not oss, f"word-boundary should block substring matches; got {oss}"


def test_missing_registry_is_honest_skip(tmp_path, monkeypatch):
    """Missing/garbage registry => rule does not fire (honest skip), never a
    crash and never a fabricated list. Verified by importing the module with a
    bad path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_bsc_mod", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_bsc_mod"] = mod  # register so @dataclass can resolve its module
    spec.loader.exec_module(mod)
    # Missing file -> empty list -> empty pattern (rule auto-skips).
    assert mod._load_oss_cores(tmp_path / "nope.json") == []
    assert mod._build_oss_pattern([]) == ""
    # Garbage JSON -> empty list.
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json")
    assert mod._load_oss_cores(bad) == []
    # cores not a list -> empty.
    notlist = tmp_path / "nl.json"
    notlist.write_text('{"cores": "picorv32"}')
    assert mod._load_oss_cores(notlist) == []


def test_corpus_sweep_no_new_oss_warn():
    """Literal corpus-sweep: the real existing backlogs corpus must gain ZERO
    oss_core_codename findings (no false-positive on legitimate data)."""
    corpus = PROG.parents[3] / "community" / "backlogs"
    if not corpus.exists():
        pytest.skip("backlogs corpus not present in this checkout")
    r = _run(["--dir", str(corpus)])
    rep = json.loads(r.stdout)
    oss = [f for f in rep["findings"] if f["category"] == "oss_core_codename"]
    assert not oss, f"corpus sweep must be free of oss_core_codename WARNs; got {oss}"


def test_skill_template_copied_verbatim_is_refused_on_plugin_version():
    """#795, second site. `community-backlog-submit/SKILL.md` shows the YAML a
    human copies. It used to ship a literal `plugin_version: '" + _shipped_version() + "'` — a
    version that is not even X.Y.Z — so a copier who changed nothing filed a
    record whose provenance was a decoration, and this gate PASSED it because
    the field was present.

    The template's `plugin_version` must now be a placeholder the gate REFUSES
    by name, so forgetting to fill it in is loud instead of silent. This test
    RUNS the gate over the template exactly as a copier would."""
    import re
    md = (PROG.parents[1] / "skills" / "community-backlog-submit" /
          "SKILL.md")
    if not md.is_file():
        pytest.skip("skill not present in this checkout")
    block = re.search(r"```yaml\n(.*?)```", md.read_text(), re.S)
    assert block, "the skill no longer shows a YAML record template"
    tpl = block.group(1)
    assert "plugin_version:" in tpl, "template dropped plugin_version"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "ORGANIC-20260804-template-copied-verbatim.yaml"
        f.write_text(tpl)
        r = _run(["--file", str(f)])
        rep = json.loads(r.stdout)
    named = [x for x in rep["findings"]
             if x["field"] == "plugin_version"
             and x["category"] == "MISSING_FIELD"]
    assert r.returncode == 1 and named, (
        "copying the documented template verbatim must FAIL naming "
        f"plugin_version; got rc={r.returncode} findings={rep['findings']}")
