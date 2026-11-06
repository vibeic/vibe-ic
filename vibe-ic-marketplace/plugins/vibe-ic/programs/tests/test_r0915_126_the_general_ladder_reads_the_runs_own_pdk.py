"""37.5ic: an unread layer table is not a forbidden layer.

R-0915-126. `tapeout_precheck`'s own arm, `general_precheck`, resolves the PDK
volume once and derives two rungs from it. `--pdk-container` is how a caller
names the container holding that volume, and the flow's clause for this step
carries none, so `container_reader(None)` read the audit HOST.

MEASURED on spm run19, from the run's own `general_precheck.json`:

    volume_read_through   "local"
    volume_tried          ["/foss/pdks/gf180mcuD", "/foss/pdks/gf180mcuD"]
    volume_resolution     "no volume for 'gf180mcuD' in the registry ..."

That directory exists in the image the run recorded and on no host. So the layer
table was unreadable, `General.ForbiddenLayers` went NOT_DETERMINED, the arm went
NOT_DETERMINED, and step 37.5ic FAILed -- over a layout whose 38 layer/datatype
pairs the rung above had just read. Reading the recorded image instead resolves
118 pairs from the technology's own file, and all 38 are inside them.

The decision is SHARED with 15.5ic rather than copied: one
`reader_the_run_recorded` in the module that owns PDK reading. Both directions
are pinned: the recorded image is read when nothing names a container, an
explicit `--pdk-container` still wins, and every way of lacking a trustworthy
receipt keeps the local reader instead of borrowing another image's answer.
"""
from __future__ import annotations

import json
import pytest
import _pdk_layer_authority as A
import general_precheck as GP

DIGEST = "ghcr.io/vibeic/vibeic-eda@sha256:" + "c" * 64


def receipt(tmp_path, **over):
    doc = {"container": "eda-run", "image_match": True,
           "require_image": DIGEST, "verdict": "PASS", "running": True}
    doc.update(over)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports/container_image.json").write_text(json.dumps(doc))
    return tmp_path


def clear(monkeypatch):
    for var in ("EDA_CONTAINER", "VIBEIC_EDA_CONTAINER"):
        monkeypatch.delenv(var, raising=False)
    import _container_exec as cex
    monkeypatch.setattr(cex, "no_container_route", lambda: False)


def test_the_recorded_image_answers_when_nothing_names_a_container(tmp_path,
                                                                   monkeypatch):
    clear(monkeypatch)
    sentinel = object()
    monkeypatch.setattr(A, "ImageReader", lambda d, runner=None: sentinel)
    reader, why = A.reader_the_run_recorded(receipt(tmp_path))
    assert reader is sentinel and DIGEST in why


def test_a_named_container_still_wins(tmp_path, monkeypatch):
    clear(monkeypatch)
    monkeypatch.setenv("EDA_CONTAINER", "eda-live")
    reader, why = A.reader_the_run_recorded(receipt(tmp_path))
    assert reader is None and "names a container" in why


@pytest.mark.parametrize("over,token", [
    ({"image_match": False}, "image_match"),
    ({"require_image": "vibeic-eda:0.3.67", "image_ref": None}, "not an identity"),
])
def test_an_untrustworthy_receipt_borrows_no_answer(tmp_path, monkeypatch, over,
                                                    token):
    clear(monkeypatch)
    reader, why = A.reader_the_run_recorded(receipt(tmp_path, **over))
    assert reader is None and token in why, why


def test_an_absent_receipt_borrows_no_answer(tmp_path, monkeypatch):
    clear(monkeypatch)
    (tmp_path / "reports").mkdir(parents=True)
    reader, why = A.reader_the_run_recorded(tmp_path)
    assert reader is None and "is absent" in why


def test_no_docker_client_asks_nothing_else(tmp_path, monkeypatch):
    clear(monkeypatch)
    import _container_exec as cex
    monkeypatch.setattr(cex, "no_container_route", lambda: True)
    reader, why = A.reader_the_run_recorded(receipt(tmp_path))
    assert reader is None and "docker" in why


def test_the_ladder_ITSELF_reads_the_recorded_image(tmp_path, monkeypatch):
    """The wiring, not just the helper. `evaluate` returns before the PDK is
    resolved when the project has no layout, so the decision is its own named
    function and is tested here directly -- otherwise a call site that stopped
    using it would break nothing."""
    clear(monkeypatch)
    sentinel = object()
    monkeypatch.setattr(A, "ImageReader", lambda d, runner=None: sentinel)
    reader, why = GP.pdk_reader_for(receipt(tmp_path), None)
    assert reader is sentinel, why
    assert DIGEST in why


def test_an_explicit_pdk_container_is_still_the_callers_word(tmp_path,
                                                            monkeypatch):
    clear(monkeypatch)
    monkeypatch.setattr(A, "ImageReader",
                        lambda d, runner=None: pytest.fail("must not be asked"))
    reader, why = GP.pdk_reader_for(receipt(tmp_path), "a-live-container")
    assert why == "the --pdk-container given"
    assert reader.name == "container:a-live-container"


def test_with_no_usable_receipt_the_ladder_keeps_the_local_reader(tmp_path,
                                                                 monkeypatch):
    """Fail-closed: no receipt means the pre-change behaviour, never another
    image's answer."""
    clear(monkeypatch)
    (tmp_path / "reports").mkdir(parents=True)
    reader, why = GP.pdk_reader_for(tmp_path, None)
    assert reader.name == "local" and "is absent" in why


def test_an_unread_layer_table_is_not_a_forbidden_layer():
    """The rung's own contract, stated as a reading rather than a verdict: with no
    volume there is no allowed set, so nothing can be called forbidden."""
    allowed, authority, tried = A.layer_table(None)
    assert not allowed and authority is None
