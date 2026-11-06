"""Native read, missing-tool and second-engine result controls."""
from __future__ import annotations

import pathlib
import subprocess
import _eda_pin as _pin
import analog_a6_native_pv as PV
import analog_a3_netlist_emit as A3
import phase3_one_shot_runner as P3

_CTN = "a-container-of-this-tests-own"


def test_a6_an_absent_container_is_NOT_MEASURED_without_a_refusal(monkeypatch):
    """THE CONTROL that keeps the two apart. An engine that could not run for
    an ordinary reason is still NOT_MEASURED — and it carries no `refusal`,
    because nothing was measured to disagree with."""
    monkeypatch.setattr(_pin, "container_image_digest",
                        lambda c: (None, f"{_pin.CONTAINER_ABSENT}: {c}"))
    got = PV.second_engine_drc(
        pathlib.Path("/nonexistent"), "blk", _CTN, "",
        runner=lambda p, b, c: (None, "the second engine did not run: nope"))
    assert got["result"] == PV.SECOND_ENGINE_NOT_MEASURED
    assert "refusal" not in got
    assert "nope" in got["reason"]

def test_a6_the_runners_own_reason_reaches_the_record():
    """It used to be dropped: `attribution, why = run(...)` and then
    `return None`, so every different failure read as one fixed sentence."""
    got = PV.second_engine_drc(
        pathlib.Path("/nonexistent"), "blk", _CTN, "",
        runner=lambda p, b, c: (None, "the attribution program wrote no report"))
    assert got["reason"] == "the attribution program wrote no report"

def test_a6_a_graded_run_is_untouched():
    """The paired control: naming the refusal must not change what a run that
    DID grade reports, or the fix would be paid for in the case it is for."""
    lyrdb = ("<report><categories><category><name>M2.b</name></category>"
             "</categories></report>")
    attribution = {"result": "LAYOUT_OWNS",
                   "by_class_and_rule": {"LAYOUT": {"a rule (MIM.i)": 8}}}
    got = PV.second_engine_drc(pathlib.Path("/nonexistent"), "blk", _CTN,
                               lyrdb, runner=lambda p, b, c: (attribution, ""))
    assert got["violations"] == 8
    assert got.get("result") != PV.SECOND_ENGINE_NOT_MEASURED

def test_a3_an_unreadable_container_is_still_reported_as_unreachable(monkeypatch):
    """THE CONTROL. A digest that could not be READ is not a mismatch, so the
    ordinary capability sentence still stands and a locally-built container is
    not locked out."""
    monkeypatch.setattr(_pin, "container_image_digest",
                        lambda c: (None, f"{_pin.CONTAINER_ABSENT}: {c}"))
    monkeypatch.setattr(A3.shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(A3, "_docker_ok", lambda _c: False)
    got = A3.verify_with_ngspice(_CTN, "blk", "* netlist\n", "* tb\n")
    assert got["simulation_status"] == "NOT_VERIFIED_NO_SIMULATOR"
    assert "is not reachable" in got["detail"]

def test_a3_docker_ok_answers_false_instead_of_raising(monkeypatch):
    """The probe itself must not throw. It is called from a `not …` expression
    with nothing around it, so a raise there is an escape all the way out."""
    monkeypatch.setattr(A3._pr, "run_best_effort",
                        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", "unreachable"))
    assert A3._docker_ok(_CTN) is False

def test_p3_an_ordinary_absence_stays_quiet_and_says_why(monkeypatch, capsys):
    """THE CONTROL. A file that is simply not there is not a refusal: it must
    not be announced, and it must still carry a reason for a caller that asks
    the primitive."""
    got = P3._v1_6_604_read_text_or_container_cat("/no/such/path.lib", "")
    assert got is None
    assert capsys.readouterr().err == ""
    _text, why = P3.read_text_or_container_cat("/no/such/path.lib", "")
    assert not why.startswith(P3.READ_REFUSED)
    assert "no container was named" in why

def test_p3_a_docker_that_will_not_run_is_a_refusal_not_an_absent_file(
        monkeypatch):
    """"I could not look" is not "I looked and it was not there"."""
    monkeypatch.setattr(_pin, "container_image_digest",
                        lambda c: (None, f"{_pin.CONTAINER_ABSENT}: {c}"))
    monkeypatch.setattr(P3.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            OSError("docker: no such file")))
    text, why = P3.read_text_or_container_cat("/no/such/path.lib", _CTN)
    assert text is None and why.startswith(P3.READ_REFUSED)
    assert "could not be run" in why

def test_p3_an_unexpected_exception_is_named_and_never_escapes(monkeypatch):
    """A runner must not be taken down by this read, and the reason must not be
    discarded either — the blanket `except Exception: pass` did both."""
    monkeypatch.setattr(_pin, "container_image_digest",
                        lambda c: (None, f"{_pin.CONTAINER_ABSENT}: {c}"))

    class _Odd(Exception):
        pass

    monkeypatch.setattr(P3.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(_Odd("boom")))
    text, why = P3.read_text_or_container_cat("/no/such/path.lib", _CTN)
    assert text is None
    assert "_Odd" in why and "boom" in why

def test_p3_a_successful_read_is_unchanged(monkeypatch, tmp_path):
    """The paired control on the happy path, host side and container side."""
    f = tmp_path / "x.lib"
    f.write_text("cell (INV) {}\n")
    assert P3._v1_6_604_read_text_or_container_cat(str(f), _CTN) == \
        "cell (INV) {}\n"

    class _CP:
        returncode = 0
        stdout = "from the container\n"
        stderr = ""

    monkeypatch.setattr(_pin, "container_image_digest",
                        lambda c: (None, f"{_pin.CONTAINER_ABSENT}: {c}"))
    monkeypatch.setattr(P3.subprocess, "run", lambda *a, **k: _CP())
    assert P3._v1_6_604_read_text_or_container_cat("/no/such/p", _CTN) == \
        "from the container\n"
