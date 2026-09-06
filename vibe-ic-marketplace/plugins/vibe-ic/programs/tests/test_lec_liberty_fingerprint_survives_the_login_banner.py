"""The EDA image's login banner was read as the sha256sum output.

MEASURED 2026-09-06 on 8HD-9, image 0.3.46. `_container_file_sha256` runs
`sha256sum` through `bash -lc`, and the image's login profile prints

    [INFO] Final PATH variable: ...
    [INFO] Final PYTHONPATH variable: ...

on stdout BEFORE the command's own output. The function took
`out.strip().split()[0]`, which is `[INFO]`, not the digest three lines down.
The 64-hex match failed, it returned None, the Liberty fingerprint was recorded
as `{"state": "unreadable"}`, `_has_fingerprint` said no,
`proof_identity_complete` said no -- and the LEC PASS CACHE WAS SILENTLY OFF
for every design whose Liberty lives in the container, which is every
Liberty-mapped LEC on this fleet. On a real run the report said
`cache: {enabled: false, reason: "one or more required proof fingerprints
unavailable"}` while sha256sum had in fact exited 0 with a correct digest.

`_strip_login_banner` is this file's OWN remedy for this exact banner, and
`_yosys_version` beside it already applied it. Only this reader did not.
"""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "lec_run.py"
sys.path.insert(0, str(SCRIPT.parent))
import lec_run  # noqa: E402

_DIGEST = "8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135"
_BANNER = (
    "[INFO] USER_ID: 1000, GROUP_ID: 0\n"
    "[INFO] Final PATH variable: /headless/.local/bin:/foss/tools/bin\n"
    "[INFO] Final PYTHONPATH variable: /headless/.local/lib/python3.12\n")


def _stub(monkeypatch, rc, out):
    monkeypatch.setattr(lec_run, "_docker_exec_raw",
                        lambda *_a, **_k: (rc, out, ""))


def test_the_digest_is_read_from_under_the_login_banner(monkeypatch):
    _stub(monkeypatch, 0, _BANNER + f"{_DIGEST}  /foss/pdks/x.lib\n")
    assert lec_run._container_file_sha256("c", "/foss/pdks/x.lib") == \
        "sha256:" + _DIGEST, (
            "the banner's first token was taken for the digest, which is how "
            "the LEC PASS cache silently switched itself off")


def test_a_bannerless_host_is_unchanged(monkeypatch):
    """The control: a host that prints no banner must behave exactly as it
    always did, so this cannot be a fix that only works on one image."""
    _stub(monkeypatch, 0, f"{_DIGEST}  /foss/pdks/x.lib\n")
    assert lec_run._container_file_sha256("c", "/foss/pdks/x.lib") == \
        "sha256:" + _DIGEST


def test_a_missing_file_is_still_None_not_a_banner_shaped_digest(monkeypatch):
    """The other direction. `None` disables REUSE and never blocks a fresh
    proof, so it must stay reachable: an absent file, a non-zero rc, and a
    banner with no digest under it are all still None."""
    _stub(monkeypatch, 1, _BANNER)
    assert lec_run._container_file_sha256("c", "/no/such.lib") is None
    _stub(monkeypatch, 0, _BANNER)
    assert lec_run._container_file_sha256("c", "/no/such.lib") is None
    _stub(monkeypatch, 0, _BANNER + "sha256sum: /no/such.lib: not found\n")
    assert lec_run._container_file_sha256("c", "/no/such.lib") is None


def test_the_identity_is_complete_once_the_liberty_hashes(monkeypatch):
    """The consequence, end to end at the predicate that gates the cache."""
    identity = {
        "recipe_schema_version": lec_run.LEC_RECIPE_SCHEMA_VERSION,
        "gold_rtl": [{"path": "a.v", "sha256": "sha256:" + "a" * 64}],
        "gate_netlist": {"path": "n.v", "sha256": "sha256:" + "b" * 64},
        "equivalence_script": {"sha256": "sha256:" + "c" * 64},
        "top": "dut",
        "scan": {"metadata": {"state": "absent"},
                 "gate_wrapper": {"state": "absent"},
                 "gold_wrapper": {"state": "absent"}},
        "liberty": {"path": "/foss/pdks/x.lib", "state": "unreadable"},
        "yosys": {"version": "Yosys 0.68+"},
        "container": {"image_digest": "sha256:image"},
    }
    assert lec_run.proof_identity_complete(identity) is False, (
        "POSITIVE CONTROL: an unreadable Liberty must still disable the cache")
    _stub(monkeypatch, 0, _BANNER + f"{_DIGEST}  /foss/pdks/x.lib\n")
    identity["liberty"] = {
        "path": "/foss/pdks/x.lib",
        "sha256": lec_run._container_file_sha256("c", "/foss/pdks/x.lib"),
    }
    assert lec_run.proof_identity_complete(identity) is True
