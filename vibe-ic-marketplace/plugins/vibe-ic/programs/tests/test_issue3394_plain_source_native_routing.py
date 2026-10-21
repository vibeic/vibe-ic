"""Regression for #3394: plain source retains the selected native executor."""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _rtl_audit_applicability as applicability
import interface_encoding_audit as producer


PLAIN = "module top(input wire a, output wire z); assign z=a; endmodule\n"


def test_plain_producer_invokes_native_owner(monkeypatch, tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text(PLAIN)
    observed = {}

    def native(modules, headers, files, top, defines, parameters,
               include_dirs, output_dir):
        observed.update(top=top, files=[Path(path).name for path in files],
                        defines=defines, parameters=parameters,
                        include_dirs=include_dirs, output_dir=output_dir)
        producer._CONFIGURATION["native"] = {
            "status": "MEASURED", "native_returncode": 0,
            "transport_returncode": 0, "image": "sha256:fixture"}
        return modules, []

    monkeypatch.setattr(producer, "_active_native_view", native)
    assert producer.run_audit(str(rtl), "top", output_dir=tmp_path / "out") == []
    assert observed == {"top": "top", "files": ["top.v"], "defines": [],
                        "parameters": [], "include_dirs": [],
                        "output_dir": tmp_path / "out"}
    assert producer._CONFIGURATION["state"] == "MEASURED"


def test_plain_subject_retains_source_level_interface_identity(monkeypatch, tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "design.v").write_text(
        "module source(input wire a, output wire z); assign z=a; endmodule\n"
        "module sink(input wire a, output wire z); assign z=a; endmodule\n"
        "module top(input wire a, output wire z); wire link; "
        "source u_source(.a(a),.z(link)); sink u_sink(.a(link),.z(z)); endmodule\n")

    def native(*_args, **_kwargs):
        raise AssertionError("an existing lexical interface is not a zero-boundary proof")

    monkeypatch.setattr(producer, "_active_native_view", native)
    rows = producer.run_audit(str(rtl), "top", output_dir=tmp_path / "out")
    edge = [row for row in rows if row.wire_name == "link"]
    assert len(edge) == 1
    assert edge[0].producer_module == "source"
    assert edge[0].consumer_module == "sink"


def test_plain_consumer_passes_executor_configuration(monkeypatch, tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text(PLAIN)
    configuration = {
        "state": "MEASURED", "top": "top", "defines": [],
        "parameters": [], "include_dirs": [],
        "native": {"status": "MEASURED", "image": "sha256:fixture",
                   "native_returncode": 0, "transport_returncode": 0},
    }
    observed = {}

    def elaborate(files, **kwargs):
        observed.update(kwargs)
        return {"modules": {"top": {
            "attributes": {}, "ports": {"a": {"bits": [1]}, "z": {"bits": [2]}},
            "netnames": {}, "cells": {}, "memories": {}}}}

    monkeypatch.setattr(applicability, "_elaborate", elaborate)
    result = applicability.assess(
        "interface_encoding_audit", rtl, top_module="top",
        configuration=configuration)
    assert result["state"] == applicability.NOT_APPLICABLE
    assert observed["selection"] is None
    assert observed["executor_configuration"] is configuration


def test_plain_consumer_retains_elaborator_refusal(monkeypatch, tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text(PLAIN)
    monkeypatch.setattr(applicability.shutil, "which", lambda _name: None)
    result = applicability.assess("interface_encoding_audit", rtl, top_module="top")
    assert result["state"] == applicability.UNKNOWN
    assert result["reason"] == "elaborator_unavailable"
