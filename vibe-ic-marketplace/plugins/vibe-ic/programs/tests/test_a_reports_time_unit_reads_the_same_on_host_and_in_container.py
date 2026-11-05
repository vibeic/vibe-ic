#!/usr/bin/env python3
"""A report's time unit must resolve the same wherever the audit runs, and a
deck's stamp must never vanish in silence.

MEASURED on spm run23, after the 2026-09-24 phase-3 re-run. The post-route
report carried its numbers in plain sight —

    worst slack max 15.20
    tns max 0.00
    worst slack min 0.55

— and `reports/phase3/sta/post_route_summary.json` published NONE of them:

    slack_measurement      "NOT_MEASURED"
    slack_values_in_ns     []
    slack_time_unit_basis  "the report names liberty
                            gf180mcu_fd_sc_mcu7t5v0__ff_n40C_5v50.lib and it
                            could not be read (FileNotFoundError); and the
                            report states no time unit of its own, so no number
                            is published under an _ns name"

`ic_release_docs_gen` then refused the whole release with STA_NO_SLACK.

TWO INDEPENDENT CAUSES, and the unit needs only one of them to survive:

  (1) THE PATH. An STA deck runs INSIDE the EDA image and stamps
      `STA_BASIS_LIBERTY: /foss/pdks/...`, a CONTAINER path. The phase-3 runner
      calls this audit on the HOST, where `/foss/pdks` does not exist. Same
      bytes, same report, different answer depending on who asked.

  (2) THE STAMP. The decks wrote the unit as
      `catch {puts $f "STA_TIME_UNIT: [sta::unit_scale_abbreviation time]..."}`.
      A failed command substitution inside `puts` fails the whole `puts`, and
      `catch` then swallows it, leaving NOTHING — indistinguishable from a deck
      that was never asked. MEASURED across run23's own reports: three carry the
      stamp and `sta_spef_based.rpt` — the one the canonical
      `post_route_timing.rpt` aliases — carries none, from the identical idiom.

A unit that genuinely cannot be established still stays NOT_MEASURED, BY NAME.
That is not what was broken; publishing nothing while the numbers sat in the
file is.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import eda_report_audit as E  # noqa: E402


_LIBERTY = 'library (x) {\n  time_unit : "1ns";\n}\n'


def _report(lib_path: str) -> str:
    return (f"STA_BASIS: POST_ROUTE_SPEF\n"
            f"STA_BASIS_LIBERTY: {lib_path}\n"
            "worst slack max 15.20\n"
            "tns max 0.00\n"
            "worst slack min 0.55\n")


# --------------------------------------------------------------- (1) THE PATH

def test_a_container_spelling_liberty_resolves_through_the_mount_map(
        tmp_path, monkeypatch):
    """THE run23 CASE. The report names the liberty as the CONTAINER saw it;
    this process is on the host. The mount docker reports is what translates
    it — not a prefix strip, not a guess."""
    host_pdk = tmp_path / "hostpdks"
    (host_pdk / "libs").mkdir(parents=True)
    lib = host_pdk / "libs" / "cell__ff_n40C_5v50.lib"
    lib.write_text(_LIBERTY)
    container_spelling = "/foss/pdks/libs/cell__ff_n40C_5v50.lib"
    assert not Path(container_spelling).exists(), (
        "this test is only meaningful while the container path is absent here")

    import _designs_root as dr
    monkeypatch.setattr(dr, "container_mounts",
                        lambda *a, **k: [(host_pdk, "/foss/pdks")])
    unit, basis = E._liberty_time_unit(_report(container_spelling))
    assert unit == "ns", (unit, basis)
    assert "mount" in basis or "resolved" in basis, basis


def test_a_liberty_readable_as_named_needs_no_translation(tmp_path,
                                                          monkeypatch):
    """IN the container the path already resolves, and nothing is consulted —
    the translation must not become a dependency of the common case."""
    lib = tmp_path / "cell.lib"
    lib.write_text(_LIBERTY)
    import _designs_root as dr

    def _boom(*a, **k):                       # pragma: no cover - must not run
        raise AssertionError("the mount map was consulted for a readable path")
    monkeypatch.setattr(dr, "container_mounts", _boom)
    unit, basis = E._liberty_time_unit(_report(str(lib)))
    assert unit == "ns", (unit, basis)


def test_no_mount_covers_it_stays_not_measured_by_name(tmp_path, monkeypatch):
    """FAIL CLOSED. A path nothing can translate is still unreadable, and the
    reason names it. A translation that cannot be made is not a unit."""
    import _designs_root as dr
    monkeypatch.setattr(dr, "container_mounts", lambda *a, **k: [])
    unit, basis = E._liberty_time_unit(
        _report("/foss/pdks/libs/nowhere__tt.lib"))
    assert unit is None
    assert "could not be read" in basis, basis
    assert "nowhere__tt.lib" in basis, basis


def test_a_broken_docker_is_not_a_unit(tmp_path, monkeypatch):
    """No daemon, no answer — and no exception escaping into the audit."""
    import _designs_root as dr

    def _raise(*a, **k):
        raise RuntimeError("docker unreachable")
    monkeypatch.setattr(dr, "container_mounts", _raise)
    unit, basis = E._liberty_time_unit(_report("/foss/pdks/x/y.lib"))
    assert unit is None and "could not be read" in basis, basis


def test_a_translated_path_that_is_still_absent_is_refused(tmp_path,
                                                           monkeypatch):
    """The mount exists and covers the path, but the file is not under it.
    Translating a name is not finding a file."""
    host = tmp_path / "hostpdks"
    host.mkdir()
    import _designs_root as dr
    monkeypatch.setattr(dr, "container_mounts",
                        lambda *a, **k: [(host, "/foss/pdks")])
    unit, basis = E._liberty_time_unit(_report("/foss/pdks/absent.lib"))
    assert unit is None and "could not be read" in basis, basis
    # ...and it must NOT claim a resolution it did not achieve. Without the
    # existence guard the outcome is the same (the open still fails) but the
    # REASON would say the path was resolved through a mount, sending a reader
    # to look for a file that is not there.
    assert "resolved to the host" not in basis, basis


# -------------------------------------------------------------- (2) THE STAMP

def test_the_reports_own_stamp_still_wins_over_the_liberty(tmp_path):
    """Unchanged precedence: a report that states its own unit is believed and
    the liberty is never opened."""
    text = ("STA_TIME_UNIT: ps\n"
            "STA_BASIS_LIBERTY: /foss/pdks/never-opened.lib\n"
            "worst slack max 15.20\n")
    unit, basis = E._sta_time_unit(text)
    assert unit == "ps", (unit, basis)
    assert "read from the report" in basis, basis


def test_every_deck_stamp_names_the_gap_instead_of_vanishing():
    """THE SECOND CAUSE, asserted on the producer's own source.

    `catch {puts ...}` leaves nothing when the substitution fails. Every site
    must compute the unit FIRST and then write a line either way, so a reader
    can tell 'this deck could not answer' from 'this deck was never asked'.
    """
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert "STA_TIME_UNIT_NOT_STATED" in src, (
        "no deck names the gap; a swallowed stamp is silent again")
    # the vanishing idiom is gone from every spelling
    assert "catch {puts $f \"STA_TIME_UNIT:" not in src
    assert "catch {puts $_bf \\\"STA_TIME_UNIT:" not in src
    assert "catch {puts $_f \\\"STA_TIME_UNIT:" not in src
    assert 'catch {puts $_f "STA_TIME_UNIT:' not in src
    # ...and every site that computes the unit also writes the else-branch
    assert src.count("STA_TIME_UNIT_NOT_STATED") == src.count(
        'catch {set _tu') == 4, (
        src.count("STA_TIME_UNIT_NOT_STATED"), src.count('catch {set _tu'))


def test_a_report_stamped_not_stated_publishes_no_number(tmp_path,
                                                         monkeypatch):
    """The named gap is a DISCLOSURE, not a unit: a report carrying
    STA_TIME_UNIT_NOT_STATED and no readable liberty still publishes nothing,
    and says which of the two it was."""
    import _designs_root as dr
    monkeypatch.setattr(dr, "container_mounts", lambda *a, **k: [])
    text = ("STA_TIME_UNIT_NOT_STATED: this interpreter could not answer\n"
            "STA_BASIS_LIBERTY: /foss/pdks/x/y.lib\n"
            "worst slack max 15.20\n")
    unit, basis = E._sta_time_unit(text)
    assert unit is None, (unit, basis)
    assert "could not be read" in basis, basis


def test_the_named_gap_reaches_the_reason_a_reader_sees(tmp_path, monkeypatch):
    """R-0915-154: the new stamp is READ, not merely written.

    The deck's `STA_TIME_UNIT_NOT_STATED` says the INTERPRETER could not
    answer — a fact about the tool, never about the design. It must reach the
    published reason, or it is a decoration nothing consumes and the registry
    row claiming a consumer would be false."""
    import _designs_root as dr
    monkeypatch.setattr(dr, "container_mounts", lambda *a, **k: [])
    text = ("STA_TIME_UNIT_NOT_STATED: this interpreter could not answer "
            "sta::unit_scale_abbreviation/unit_suffix for time\n"
            "STA_BASIS_LIBERTY: /foss/pdks/x/y.lib\n"
            "worst slack max 15.20\n")
    unit, basis = E._sta_time_unit(text)
    assert unit is None, (unit, basis)
    assert "the deck stated it could not establish the unit" in basis, basis
    assert "sta::unit_scale_abbreviation" in basis, basis


def test_a_deck_gap_does_not_override_a_readable_liberty(tmp_path,
                                                         monkeypatch):
    """Precedence: the deck could not answer, but the liberty CAN. The unit is
    established, and the deck's gap is still disclosed beside it — one source
    failing is not the measurement failing."""
    lib = tmp_path / "cell.lib"
    lib.write_text(_LIBERTY)
    text = (f"STA_TIME_UNIT_NOT_STATED: interpreter could not answer\n"
            f"STA_BASIS_LIBERTY: {lib}\n"
            "worst slack max 15.20\n")
    unit, basis = E._sta_time_unit(text)
    assert unit == "ns", (unit, basis)
    assert "the deck stated it could not establish the unit" in basis, basis


# ============================================================================
# (3) THE PDK IS IMAGE CONTENT, NOT A MOUNT — review wrb6czvv3.
#
# The first cut translated mounts and its test FAKED one, so it proved nothing
# about the real case. MEASURED on this host: the EDA container reports mounts
# for the lane and for /foss/designs and NONE covering /foss/pdks; the liberty
# lives at /foss/pdks/... INSIDE the image (20,416,204 bytes, time_unit at byte
# offset 769) and exists on the host at no spelling. A host-side audit that
# only translates mounts therefore still refuses — which is exactly what run23
# did. These arms use the REAL path, with no mount faked anywhere.
# ============================================================================

import json as _json  # noqa: E402
import os as _os      # noqa: E402
import shutil as _shutil  # noqa: E402
import subprocess as _sp  # noqa: E402

import pytest  # noqa: E402

from _tool_probes import skip_not_verified  # noqa: E402

# WHICH SKIPS HERE ARE NOT-VERIFIED, AND WHICH ONE IS NOT (vibe-ic#1128)
# ======================================================================
# `_image_ref_or_skip` fires when the thing these arms verify WITH is out of
# reach — no docker CLI, no resolvable pin, the pinned image not pulled. Each
# of those is an UNANSWERED question about the image-read path, so each
# declares through the tier and carries the command that would answer it.
#
# `_skip_unless_image_content` is deliberately NOT in the tier. It fires where
# the liberty opens directly, and there the arms do not merely go unverified —
# they do not APPLY: there is no mount to translate and no image to read from,
# so the host case they exist for is absent. Annexing an ordinary N/A into this
# tier is the over-reach `not_verified_tier`'s own docstring rules out, and it
# would make an in-image run report an unanswered question it does not have.
# Every caller runs that check FIRST, so an in-image run never reaches the
# declarations below.

#: The liberty spm run23 actually timed against, as the deck stamped it.
_IMAGE_LIBERTY = (
    "/foss/pdks/ciel/gf180mcu/versions/"
    "b344c97eacc2aaf8e14ae7e43e2e9dc0871de2c0/gf180mcuD/libs.ref/"
    "gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__ff_n40C_5v50.lib")


def _image_ref_or_skip() -> str:
    """The pinned image, or skip — this arm needs the real one."""
    if not _shutil.which("docker"):
        skip_not_verified(
            "docker is not available here, so the image-read path this arm "
            "exists to prove was never exercised",
            "install the docker CLI on this host and re-run this file")
    try:
        import _eda_pin as _pin
        ref = _pin.image_reference()
    except Exception as exc:                                 # noqa: BLE001
        skip_not_verified(
            f"the pinned image reference could not be resolved ({exc}), so "
            f"there was no image to read the liberty from",
            "repair programs/_eda_pin.py so image_reference() resolves, then "
            "re-run this file")
    if not ref:
        skip_not_verified(
            "_eda_pin.image_reference() names no image, so there was no "
            "image to read the liberty from",
            "pin an EDA image reference in programs/_eda_pin.py, then re-run "
            "this file")
    r = _sp.run(["docker", "image", "inspect", ref],
                capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        skip_not_verified(
            f"the pinned image is not present locally ({ref}), so the "
            f"liberty could not be read from the image the run recorded",
            f"docker pull {ref}")
    return ref


def _skip_unless_image_content() -> None:
    """These arms are about the HOST case and only exist there.

    Run INSIDE the EDA image the path is ordinary image content and opens
    directly, so there is nothing to translate and nothing to read from an
    image — the arms would pass for the wrong reason. The suite's own harness
    runs in that image, so they skip there and are exercised on the host.
    That asymmetry is the POINT of this fix and is stated rather than hidden.
    """
    if Path(_IMAGE_LIBERTY).exists():
        pytest.skip("running where the PDK is already readable (in-image); "
                    "these arms exercise the host case")


def test_the_pdk_path_is_image_content_not_a_mount():
    """THE PREMISE, measured rather than assumed: wherever this runs, the
    liberty is reachable EITHER directly (in-image) OR only through the image.
    It is never a bind mount — no mount on this fleet covers /foss/pdks, which
    is why translating mounts alone could not answer."""
    import _designs_root as dr
    try:
        mounts = dr.container_mounts()
    except Exception:                                        # noqa: BLE001
        mounts = []
    covering = [d for _s, d in mounts
                if str(d).rstrip("/") and _IMAGE_LIBERTY.startswith(
                    str(d).rstrip("/") + "/")]
    assert not covering, (
        f"a mount now covers the PDK ({covering}); the image-read path is no "
        f"longer the only answer and this fix needs re-deriving")


def test_an_image_internal_liberty_is_read_from_the_runs_own_image(tmp_path):
    """THE run23 CASE, for real: no mount is faked, the path is image content,
    and the image is the one the RUN recorded — not a default container."""
    _skip_unless_image_content()
    ref = _image_ref_or_skip()
    project = tmp_path / "run"
    (project / "reports").mkdir(parents=True)
    (project / "reports" / "container_image.json").write_text(
        _json.dumps({"container": "irrelevant-to-this-read",
                     "image_ref": ref}))
    unit, basis = E._liberty_time_unit(_report(_IMAGE_LIBERTY),
                                       project=project)
    assert unit == "ns", (unit, basis)
    assert "read from image" in basis, basis
    assert ref in basis, basis


def test_the_explicit_image_beats_the_runs_record(tmp_path):
    """`--image` states it outright; the run's record is the fallback, and the
    caller's word wins when both are present."""
    _skip_unless_image_content()
    ref = _image_ref_or_skip()
    project = tmp_path / "run"
    (project / "reports").mkdir(parents=True)
    (project / "reports" / "container_image.json").write_text(
        _json.dumps({"image_ref": "ghcr.io/vibeic/vibeic-eda@sha256:" + "0" * 64}))
    unit, basis = E._liberty_time_unit(_report(_IMAGE_LIBERTY),
                                       project=project, image=ref)
    assert unit == "ns", (unit, basis)
    assert ref in basis, basis


def test_no_recorded_image_stays_not_measured_by_name(tmp_path):
    """A run that never recorded what it ran against cannot have its
    image-internal PDK read, and says so — it does not fall back to a default
    container, which would answer a different question."""
    _skip_unless_image_content()
    project = tmp_path / "run"
    (project / "reports").mkdir(parents=True)
    unit, basis = E._liberty_time_unit(_report(_IMAGE_LIBERTY),
                                       project=project)
    assert unit is None
    assert "could not be read" in basis, basis
    assert "container_image.json" in basis, basis


def test_an_unreachable_image_stays_not_measured_by_name(tmp_path):
    """A recorded image that is not here is not a unit."""
    _skip_unless_image_content()
    if not _shutil.which("docker"):
        skip_not_verified(
            "docker is not available here, so 'a recorded image that is not "
            "present stays NOT_MEASURED' was never put to the test",
            "install the docker CLI on this host and re-run this file")
    project = tmp_path / "run"
    (project / "reports").mkdir(parents=True)
    (project / "reports" / "container_image.json").write_text(
        _json.dumps({"image_ref":
                     "ghcr.io/vibeic/vibeic-eda@sha256:" + "0" * 64}))
    unit, basis = E._liberty_time_unit(_report(_IMAGE_LIBERTY),
                                       project=project)
    assert unit is None, (unit, basis)
    assert "could not be read" in basis, basis


def test_the_cli_carries_the_image_to_the_reader():
    """Requirement 4: the caller states the image explicitly. The flag exists,
    and setting it reaches the module the reader consults."""
    src = (PROGRAMS / "eda_report_audit.py").read_text()
    assert '"--image"' in src, "no --image flag to pass the run's image with"
    assert "set_image_override(" in src, "the flag does not reach the reader"
    E.set_image_override("ghcr.io/x@sha256:" + "1" * 64)
    try:
        assert E._STA_IMAGE_OVERRIDE == "ghcr.io/x@sha256:" + "1" * 64
    finally:
        E.set_image_override(None)
    assert E._STA_IMAGE_OVERRIDE is None
