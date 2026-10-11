"""`identity.openroad_commit` comes from the OpenROAD builds that ran.

Review wave 58 DRVSTACK (correctness): the judge requires it, nothing produced
it, so every real capture was NOT_MEASURED ("openroad_commit absent" on the
real spm run) whatever the design. The capture now asks every OpenROAD build of
the pinned image for its version (the LibreLane dispatcher runs `openroad-python`
for its scripts, the direct deck runs `openroad`) and records the commit only
when they agree.
"""
import json
import os
import re
import subprocess
import sys
import pytest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import drv_signoff_capture as C  # noqa: E402
from not_verified_tier import skip_not_verified  # noqa: E402

_LINE = "OPENROAD_BINARY {p} {s} {v}\n"
_SHA = "a" * 64


def _answer(text):
    return lambda argv, **k: SimpleNamespace(returncode=0, stdout=text, stderr="")


@pytest.mark.parametrize('version,commit', [
    ('26Q3-3055-gb73fad7a92', 'b73fad7a92'),
    ('b' * 40, 'b' * 40),
])
def test_two_builds_of_one_version_give_its_commit(version, commit):
    rec = C.openroad_identity("img", run=_answer(
        _LINE.format(p="/t/openroad", s=_SHA, v=version)
        + _LINE.format(p="/t/openroad-python", s="b" * 64, v=version)))
    assert rec["commit"] == commit and len(rec["binaries"]) == 2


def test_builds_that_disagree_give_no_commit():
    rec = C.openroad_identity("img", run=_answer(
        _LINE.format(p="/t/openroad", s=_SHA, v="26Q3-3055-gb73fad7a92")
        + _LINE.format(p="/t/openroad-python", s=_SHA, v="26Q3-3001-g0123456789")))
    assert rec["commit"] is None and "different versions" in rec["reason"]


@pytest.mark.parametrize('version', ['2.0', 'HEAD-HASH-NOTFOUND', 'b' * 7])
def test_a_version_without_a_commit_or_no_answer_gives_none(version):
    assert C.openroad_identity("img", run=_answer(
        _LINE.format(p="/t/openroad", s=_SHA, v=version)))["commit"] is None
    assert C.openroad_identity("img", run=_answer("bash: openroad: not found\n"))[
        "commit"] is None


def test_the_capture_records_it_in_the_identity_the_judge_reads(tmp_path, monkeypatch):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if argv[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
                {"Id": "sha256:" + "c" * 64, "Config": {"Labels": {}}}))
        return SimpleNamespace(returncode=0, stderr="", stdout=_LINE.format(
            p="/t/openroad", s=_SHA, v="26Q3-3055-gb73fad7a92"))
    monkeypatch.setattr(C.subprocess, "run", run)
    monkeypatch.setattr(C, "image_pdk_anchor",
                        lambda *a: (_ for _ in ()).throw(ValueError("no anchor")))
    plan = {"identity": {"pdk": "p", "library": "l", "artifacts": {}},
            "frozen": {}, "current": {}, "stages": [], "pins": {}, "scenes": []}
    bundle = C.capture(plan, tmp_path / "cap", image="img")
    assert bundle["identity"]["openroad_commit"] == "b73fad7a92"
    assert bundle["identity"]["openroad_build"]["binaries"][0]["sha256"] == _SHA


def test_the_real_builds_in_the_pinned_image_name_their_commit():
    """The probe against the image the flow pins, not a transcript."""
    import shutil
    import _eda_pin
    image = _eda_pin.image_reference()
    if shutil.which("docker") is None or subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True).returncode:
        skip_not_verified(f"docker or the pinned image {image} is not on host "
                          f"{os.uname().nodename}", "run on a lane host holding the image")
    rec = C.openroad_identity(image)
    assert rec["binaries"], rec
    assert re.fullmatch(r"[0-9a-f]{7,40}", rec["commit"] or ""), rec
    assert all(b["version"].endswith("-g" + rec["commit"]) or
               b["version"] == rec["commit"] for b in rec["binaries"])
