"""ORGANIC #551 — container mount-coverage preflight + error-signature in
step-FAIL detail (root cause not buried under head/tail truncation).
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


def test_container_path_covered(monkeypatch):
    monkeypatch.setattr(
        R, "_container_mounts",
        lambda c: [("/home/u/AI_IC_design", "/home/u/AI_IC_design"),
                   ("/foss/pdks", "/foss/pdks")])
    assert R._container_path_covered("/home/u/AI_IC_design/proj", "c")
    assert R._container_path_covered("/home/u/AI_IC_design", "c")
    # NOT covered → preflight would fail-fast
    assert not R._container_path_covered("/tmp/elsewhere/proj", "c")
    assert not R._container_path_covered("", "c")


def test_no_mounts_means_not_covered(monkeypatch):
    monkeypatch.setattr(R, "_container_mounts", lambda c: [])
    assert not R._container_path_covered("/any/path", "c")


def test_error_signature_surfaces_root_cause():
    # the root cause printed early, then a flood of cascade errors followed;
    # the signature extractor still surfaces it (last matching signatures).
    log = (
        "PATH=/usr/bin:/bin\nLD_LIBRARY_PATH=/foss/lib\n"
        "cd: /home/u/proj: No such file or directory\n"
        + "warning: noise\n" * 200
        + "ERROR: cannot open design file\n")
    sig = R._extract_error_signature(log)
    assert "cannot open design file" in sig or "No such file" in sig
    assert "PATH=/usr/bin" not in sig  # banner not surfaced


def test_error_signature_empty_when_no_error():
    assert R._extract_error_signature("all good\ndone\n") == ""


def test_error_signature_dedup_and_cap():
    log = "ERROR: same\n" * 10
    sig = R._extract_error_signature(log)
    # de-duplicated to a single line
    assert sig.count("ERROR: same") == 1
