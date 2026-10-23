"""Actual frozen RC input; bounded A8 caller and consumer controls.

The native-call doubles below test wiring, never claim measured performance.
"""
from pathlib import Path
import hashlib
import json
import re
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_a8_hardmacro_emit as E
import _analog_a_check_common as C
import analog_a8_hardmacro_gen_check as G

FIXTURE = Path(__file__).parent / "fixtures/a8_native_rc_wrapper"
RAW_SHA = "d287657852a25340b685e3884207c4bc8153110d08cba44dc598a2dc2a41bbc6"


def _project(tmp_path, *, coherent=True):
    project = tmp_path / "project"
    b = project / "phase3/analog/ldo_open"
    shutil.copytree(FIXTURE, b)
    (b.parent / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo_open", "type": "ldo"}]}))
    if coherent:
        # Explicit UNIT derivative: original staged spec has extra vbias,
        # which the existing A3 subject gate correctly refuses. Keep original
        # fixture bytes in git; only this private caller-control input changes.
        spec = b / "spec.json"
        doc = json.loads(spec.read_text())
        doc["interface"]["pins"] = [p for p in doc["interface"]["pins"] if p["name"] != "vbias"]
        spec.write_text(json.dumps(doc))
        sidecar = b / "netlist_provenance.json"
        doc = json.loads(sidecar.read_text())
        doc["_provenance"]["rendered_from"]["spec_json"]["sha256"] = E._sha256(spec)
        sidecar.write_text(json.dumps(doc))
    # Unit-only transport inputs, not native layout/measurement receipts.
    (b / "layout.mag").write_text("magic\ntech sky130A\n")
    (b / "ldo_open.gds").write_bytes(b"unit-only-gds")
    topo = json.loads((b / "topology.json").read_text())
    return project, b, topo


def _transport(monkeypatch, project, b, topo, *, fail=False, mutate=None):
    calls = []
    monkeypatch.setattr(E, "magicrc_for", lambda *a: "/pdk/sky130A.magicrc")
    monkeypatch.setattr(E, "_native_model_contract", lambda *a: (
        {"path": "/pdk/model.lib", "section": "tt", "sha256": "a" * 64}, ""))
    monkeypatch.setattr(E, "_remote_sha256", lambda *a: ("a" * 64, ""))
    monkeypatch.setattr(E, "_native_ngspice_binary", lambda *a: ("/usr/bin/ngspice", ""))
    monkeypatch.setattr(E, "_runtime_image_digest", lambda *a: ("sha256:" + "b" * 64, ""))

    def transport(container, cmd, timeout=900, *, marker=None, log_path=None):
        if marker == "a8_extract.tcl":
            shutil.copyfile(FIXTURE / "a8_post_layout_extracted.spice",
                            b / ".a8_native_stage/ldo_open_extracted.spice")
            return 0, "unit extraction transport", ""
        if marker == "a8_native_measurement.sp":
            calls.append(cmd)
            raw = b / "a8_post_layout_extracted.spice"
            deck = (b / marker).read_text()
            assert f'.include "{raw}"' in deck
            wrapper = b / "a8_extraction_wrapper.spice"
            assert f'.include "{wrapper}"' in deck
            assert "XU vdd 0 vref vout ldo_open__a8_interface" in deck
            assert "v_vdd vdd 0 1.8" in deck and "v_vref vref 0 0.6" in deck
            assert hashlib.sha256(raw.read_bytes()).hexdigest() == RAW_SHA
            assert "Xnative" in wrapper.read_text()
            if mutate:
                mutate(b)
            if fail:
                (b / "a8_native_ngspice.log").write_text("Error: unresolved physical bulk\n")
                return 1, "", "native failure preserved"
            (b / "a8_native_ngspice.log").write_text("unit ngspice transport\npwr = 0.0005\n")
            return 0, "", ""
        if marker == "ldo_open_lef.tcl":
            h = project / "phase3/analog/hardmacro/ldo_open"
            pins = "\n".join(f"PIN {p}\n PORT\n LAYER Metal3 ;\n RECT 0 0 1 1 ;\n END\nEND {p}"
                             for p in topo["ports"])
            output = Path(re.search(r"(?m)^lef write (.+) -hide$", (h / marker).read_text()).group(1))
            output.write_text(f"MACRO ldo_open\nSIZE 4 BY 4 ;\n{pins}\nEND ldo_open\n")
            return 0, "unit LEF transport", ""
        raise AssertionError(f"unexpected native command: {cmd}")

    monkeypatch.setattr(E, "_docker_exec", transport)
    return calls


def _emitted(tmp_path, monkeypatch):
    project, b, topo = _project(tmp_path)
    calls = _transport(monkeypatch, project, b, topo)
    got = E.emit_block(project, "ldo_open", "", "/pdk")
    assert got["rc"] == 0 and got["emitted"], got
    assert len(calls) == 1
    assert C.hardmacro_content(b).klass == "structure_only"
    return project, b, topo


def _record(b):
    return json.loads((b / E._A8_MEASUREMENT).read_text())


def _save(b, rec):
    (b / E._A8_MEASUREMENT).write_text(json.dumps(rec))


def test_actual_full_header_normal_caller_and_consumers(tmp_path, monkeypatch):
    project, b, topo = _emitted(tmp_path, monkeypatch)
    rec, why = E.load_native_measurement(project, "ldo_open", b / "ldo_open.gds", topo)
    assert rec is not None, why
    wrapper = rec["extraction_wrapper"]
    assert len(wrapper["native_ports"]) == 143
    assert len(wrapper["instance_nodes"]) == 143
    assert wrapper["instance_nodes"][:4] == topo["ports"]
    assert len(set(wrapper["instance_nodes"][4:])) == 139
    assert wrapper["native_subckt"] != wrapper["wrapper_subckt"]
    manifest = json.loads((project / "phase3/analog/hardmacro/ldo_open/a8_views_provenance.json").read_text())
    assert manifest["native_measurement"]["extraction_wrapper"] == wrapper
    # The manifest field names the measurement JSON bytes themselves.  It must
    # not be the digest of the wrapper file consumed by the deck.
    measurement_file = b / E._A8_MEASUREMENT
    assert manifest["native_measurement"]["sha256"] == \
        hashlib.sha256(measurement_file.read_bytes()).hexdigest()
    report = project / "fresh-explicit-a8.json"
    rc = G.main([str(project), "--block", "ldo_open", "--json", str(report)])
    assert rc == 0
    assert json.loads(report.read_text())["verdict"] == "PASS_STRUCTURE_ONLY"


def test_raw_network_and_open_bulk_are_preserved(tmp_path):
    project, b, topo = _project(tmp_path)
    raw = b / "a8_post_layout_extracted.spice"
    before = raw.read_bytes()
    # Test actual immutable raw mapping independently of subject admission.
    wrapper, contract = E._aw.build_wrapper(before.decode(), "ldo_open", topo["ports"])
    assert raw.read_bytes() == before and E._sha256(raw) == RAW_SHA
    lines = E._aw.logical_lines(before.decode())
    counts = {kind: sum(ln.startswith(kind) for ln in lines) for kind in ("R", "C", "X")}
    assert counts["R"] > 0 and counts["C"] > 0 and counts["X"] > 0
    combined = E._aw.logical_lines(before.decode() + "\n" + wrapper)
    assert {kind: sum(ln.startswith(kind) for ln in combined) for kind in ("R", "C")} == {
        kind: counts[kind] for kind in ("R", "C")}
    # Only the hierarchy instance is new; every original device stays byte-identical.
    assert sum(ln.startswith("X") for ln in combined) == counts["X"] + 1
    map_ = dict(zip(contract["native_ports"], contract["instance_nodes"]))
    assert len(map_) == len(set(map_.values())) == 143
    # R-only top-level body map reproduces the existing physical open, rather
    # than treating a new wrapper node as a ground or shorting a finite R.
    graph = {}
    top = False
    for line in lines:
        if line.startswith(".subckt ldo_open "):
            top = True
        elif top and line.lower().startswith(".ends"):
            break
        elif top and line.startswith("R"):
            _, a, c, value = line.split()[:4]
            assert float(value) > 0
            graph.setdefault(a, set()).add(c)
            graph.setdefault(c, set()).add(a)
    def component(seed):
        found, pending = set(), [seed]
        while pending:
            n = pending.pop()
            if n not in found:
                found.add(n)
                pending.extend(graph.get(n, set()) - found)
        return found
    assert not component("d9/B").intersection(topo["ports"])
    for body in ("d5/B", "d6/B", "d7/B"):
        assert not component(body).intersection(topo["ports"])
    # A bijection preserves R reachability, including the same missing rail.
    mapped_component = {map_.get(n, "native:" + n) for n in component("d9/B")}
    assert not mapped_component.intersection(topo["ports"])


@pytest.mark.parametrize("extra_count", [1, 139, 256, 300])
def test_current_header_length_is_derived(extra_count):
    ports = ["vdd", "vss", "vref", "vout"]
    raw = ".subckt dut " + " ".join(ports) + "\n"
    raw += "\n".join("  + rc" + str(i) for i in range(extra_count)) + "\n.ends dut\n"
    text, mapping = E._aw.build_wrapper(raw, "dut", ports)
    assert len(mapping["native_ports"]) == 4 + extra_count
    assert len(set(mapping["instance_nodes"])) == 4 + extra_count
    assert E._aw.native_ports(text, "dut__a8_interface") == ports


@pytest.mark.parametrize("mutation", ["duplicate_native", "duplicate_declared", "missing_declared",
                                      "duplicate_top", "name_collision", "node_collision", "global", "unterminated"])
def test_ambiguous_interfaces_refuse(mutation):
    ports = ["vdd", "vss", "vref", "vout"]
    raw = ".subckt dut vdd vss vref vout\n+ rc\n.ends dut\n"
    if mutation == "duplicate_native":
        raw = raw.replace("+ rc", "+ VDD")
    elif mutation == "duplicate_declared":
        ports[-1] = "VDD"
    elif mutation == "missing_declared":
        raw = raw.replace("vref", "other")
    elif mutation == "duplicate_top":
        raw += raw.replace("dut", "DUT")
    elif mutation == "name_collision":
        raw += ".subckt dut__a8_interface a b\n.ends\n"
    elif mutation == "node_collision":
        ports[-1] = "a8_rc_p0004"
        raw = raw.replace("vout", ports[-1])
    elif mutation == "global":
        raw += ".global rc\n"
    elif mutation == "unterminated":
        raw = raw.replace(".ends dut", "")
    with pytest.raises(ValueError):
        E._aw.build_wrapper(raw, "dut", ports)


@pytest.mark.parametrize("mutation", ["raw_missing", "raw_changed", "wrapper_missing", "wrapper_changed", "wrapper_bytes",
                                      "mapping", "short", "order", "wrapper_removed", "deck_missing",
                                      "deck_bypass", "a3", "a3_fresh", "sidecar", "a3_ports", "topology"])
def test_current_group_mutations_refuse(tmp_path, monkeypatch, mutation):
    project, b, topo = _emitted(tmp_path, monkeypatch)
    rec = _record(b)
    wrapper = b / "a8_extraction_wrapper.spice"
    raw = b / "a8_post_layout_extracted.spice"
    deck = b / "a8_native_measurement.sp"
    if mutation.endswith("_missing"):
        {"raw_missing": raw, "wrapper_missing": wrapper, "deck_missing": deck}[mutation].unlink()
    elif mutation == "raw_changed":
        raw.write_text(raw.read_text().replace("R0 ", "Rchanged ", 1))
    elif mutation == "wrapper_bytes":
        wrapper.write_text(wrapper.read_text() + "* wrapper byte drift\n")
    elif mutation == "wrapper_changed":
        wrapper.write_text(wrapper.read_text() + "* forged wrapper\n")
        rec["extraction_wrapper"]["sha256"] = E._sha256(wrapper)
    elif mutation in ("mapping", "short", "order"):
        nodes = rec["extraction_wrapper"]["instance_nodes"]
        if mutation == "mapping":
            nodes[-1] = "invented"
        elif mutation == "short":
            nodes[-1] = nodes[-2]
        else:
            nodes[-1], nodes[-2] = nodes[-2], nodes[-1]
    elif mutation == "wrapper_removed":
        del rec["extraction_wrapper"]
        rec.pop("measurement_deck")
        rec.pop("measurement_deck_sha256")
    elif mutation == "deck_bypass":
        text = deck.read_text()
        assert text.count("XU vdd 0 vref vout ldo_open__a8_interface") == 1
        deck.write_text(text.replace("XU vdd 0 vref vout ldo_open__a8_interface",
                                     "XU vdd 0 vref vout ldo_open"))
        rec["measurement_deck_sha256"] = E._sha256(deck)
    elif mutation == "a3":
        (b / "ldo_open.sp").write_text((b / "ldo_open.sp").read_text() + "* current drift\n")
    elif mutation == "a3_fresh":
        a3 = b / "ldo_open.sp"
        a3.write_text(a3.read_text() + "* fresh current subject\n")
        sidecar = b / "netlist_provenance.json"
        doc = json.loads(sidecar.read_text())
        doc["_provenance"]["artifact_sha256"] = E._sha256(a3)
        sidecar.write_text(json.dumps(doc))
    elif mutation == "sidecar":
        (b / "netlist_provenance.json").unlink()
    elif mutation == "a3_ports":
        a3 = b / "ldo_open.sp"
        a3.write_text(a3.read_text().replace(".subckt ldo_open vdd vss vref vout", ".subckt ldo_open vdd vss vout vref"))
        sidecar = b / "netlist_provenance.json"
        doc = json.loads(sidecar.read_text())
        doc["_provenance"]["artifact_sha256"] = E._sha256(a3)
        sidecar.write_text(json.dumps(doc))
    elif mutation == "topology":
        topo["ports"][-1] = "other"
        (b / "topology.json").write_text(json.dumps(topo))
    _save(b, rec)
    loaded, why = E.load_native_measurement(project, "ldo_open", b / "ldo_open.gds", topo)
    assert loaded is None, (mutation, why)
    assert C.hardmacro_content(b).klass == "undisclosed"


@pytest.mark.parametrize("field", ["extraction_wrapper", "measurement_deck", "measurement_deck_sha256"])
def test_manifest_cannot_omit_consumed_group(tmp_path, monkeypatch, field):
    project, b, topo = _emitted(tmp_path, monkeypatch)
    manifest = project / "phase3/analog/hardmacro/ldo_open/a8_views_provenance.json"
    doc = json.loads(manifest.read_text())
    del doc["native_measurement"][field]
    manifest.write_text(json.dumps(doc))
    assert E.load_native_measurement(project, "ldo_open", b / "ldo_open.gds", topo)[0] is not None
    assert C.hardmacro_content(b).klass == "undisclosed"
    status, _ = G._check_block(project, "ldo_open")
    assert status == "FAIL"


def test_native_failure_never_becomes_measurement(tmp_path, monkeypatch):
    project, b, topo = _project(tmp_path)
    calls = _transport(monkeypatch, project, b, topo, fail=True)
    rec, why = E._native_measurement_produce(project, "ldo_open", "", "/pdk", b / "ldo_open.gds", topo)
    assert rec is None and "ngspice rc=1" in why
    assert len(calls) == 1 and not (b / E._A8_MEASUREMENT).exists()
    assert E._sha256(b / "a8_post_layout_extracted.spice") == RAW_SHA
    assert C.hardmacro_content(b).klass == "undisclosed"


@pytest.mark.parametrize("file", ["a8_extraction_wrapper.spice", "a8_post_layout_extracted.spice", "ldo_open.sp"])
def test_native_input_mutation_refuses_publication(tmp_path, monkeypatch, file):
    project, b, topo = _project(tmp_path)
    def mutate(b):
        path = b / file
        path.write_text(path.read_text() + "* changed during native call\n")
    _transport(monkeypatch, project, b, topo, mutate=mutate)
    rec, why = E._native_measurement_produce(project, "ldo_open", "", "/pdk", b / "ldo_open.gds", topo)
    assert rec is None and "changed" in why
    assert not (b / E._A8_MEASUREMENT).exists()


def test_original_actual_a3_spec_mismatch_keeps_refusal(tmp_path, monkeypatch):
    project, b, topo = _project(tmp_path, coherent=False)
    calls = _transport(monkeypatch, project, b, topo)
    result = E.emit_block(project, "ldo_open", "", "/pdk")
    assert result["rc"] == 1 and "spec interface pins" in result["reason"]
    assert not calls and not (b / E._A8_MEASUREMENT).exists()
    assert C.hardmacro_content(b).klass == "undisclosed"
    assert E._sha256(b / "a8_post_layout_extracted.spice") == RAW_SHA


def test_actual_fixed_contact_260_header_and_network_preserved():
    raw = (FIXTURE / "fixed_contact_260.spice").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "8cf5563be04e3d3aa6fcf9bd56645c37367be0fe2f6c2be8f1226e9e778b16b7"
    declared = ["vdd", "vss", "vref", "vout"]
    text, contract = E._aw.build_wrapper(raw.decode(), "ldo_open", declared)
    assert len(contract["native_ports"]) == 260
    assert len(set(contract["instance_nodes"])) == 260
    # Magic's current 260-port order differs from the declared interface order.
    # Bind each declared pin at its actual native position, never first-four.
    for pin in declared:
        assert contract["instance_nodes"][contract["native_ports"].index(pin)] == pin
    assert E._aw.native_ports(text, "ldo_open__a8_interface") == declared
    before = E._aw.logical_lines(raw.decode())
    after = E._aw.logical_lines(raw.decode() + "\n" + text)
    for kind, count in (("R", 639), ("C", 554)):
        assert sum(line.startswith(kind) for line in before) == count
        assert sum(line.startswith(kind) for line in after) == count
    assert sum(line.startswith("X") for line in after) == sum(line.startswith("X") for line in before) + 1
    assert (FIXTURE / "fixed_contact_260.spice").read_bytes() == raw
