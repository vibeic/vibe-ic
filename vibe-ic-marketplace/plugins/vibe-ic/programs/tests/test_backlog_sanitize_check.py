#!/usr/bin/env python3
"""Tests for backlog_sanitize_check.py"""
from __future__ import annotations
import json
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "backlog_sanitize_check.py"
REGISTRY = PROG.parent / "oss_core_registry.json"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_clean_yaml(tmp_path):
    bf = tmp_path / "backlog.yaml"
    bf.write_text("type: enhancement\ncomponent: skill:spec-to-rtl\ntitle: Add SPI timeout\npattern: SPI clock recovery should handle jitter\nplugin_version: '0.115'\n")
    r = _run(["--file", str(bf)])
    assert r.returncode == 0

def test_empty_dir(tmp_path):
    r = _run(["--dir", str(tmp_path)])
    assert r.returncode == 0


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
        "plugin_version: '0.225'\n"
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
        "plugin_version: '0.225'\n"
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
        "plugin_version: '0.225'\n"
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
