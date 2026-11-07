"""Product labels cannot select the authored RTL module."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import phase1_doc_one_shot_runner as phase1
from flow_config import resolve_rtl_inputs


def emit(project, product="PulseBox", declaration=""):
    text = f"# {product}\nA four-channel pulse generator.\n{declaration}\n"
    path = project / "input/docs/design_description.md"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    docs = {str(path): text}
    phase1.gen_l1_datasheet(project, docs)
    l1 = project / "phase1/generated_docs/L1_DATASHEET.json"
    assert json.loads(l1.read_text())["ic_name"] == product
    result = phase1.gen_l9_integration_spec(project, docs, {})
    return Path(result.path)


@pytest.mark.parametrize("product", ["PulseBox", "PacketHub", "SerialDevice"])
def test_product_name_does_not_declare_a_module(tmp_path, product):
    l9 = json.loads(emit(tmp_path, product).read_text())
    assert l9["top_module"] is None
    assert l9["top_module_extraction_strategy"] == phase1.TOP_MODULE_UNDECLARED_STRATEGY
    assert l9["top_module_status"] == phase1.TOP_MODULE_STATUS_UNDECLARED
    assert l9["no_top_module_in_input"] is True


@pytest.mark.parametrize("declaration", [
    "The top module is `documented_shell`.",
    "Top module: `documented_shell`",
])
def test_real_module_declaration_wins_over_product_label(tmp_path, declaration):
    l9 = json.loads(emit(tmp_path, declaration=declaration).read_text())
    assert l9["top_module"] == "documented_shell"
    assert l9["top_module_status"] == phase1.TOP_MODULE_STATUS_DECLARED
    assert l9["no_top_module_in_input"] is False


@pytest.fixture(params=["unstated", "legacy_product"])
def authored(tmp_path, request):
    path = emit(tmp_path)
    if request.param == "legacy_product":
        l9 = json.loads(path.read_text())
        l9.update(top_module="PulseBox",
                  top_module_extraction_strategy="l1_ic_name_fallback",
                  top_module_status="derived_from_chip_name")
        path.write_text(json.dumps(l9))
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    # A unique top authored after Phase 1, with a name unrelated to the product.
    (rtl / "chip_top.v").write_text(
        "module chip_top(input wire a, output wire z); assign z=a; endmodule\n")
    return tmp_path, path


def test_authored_top_replaces_unstated_strategy_and_keeps_input_absence(authored):
    project, path = authored
    files, top, _ = resolve_rtl_inputs(project)
    assert top == "chip_top"
    assert files == [project / "phase2/stage1/rtl/chip_top.v"]
    resolved = json.loads(path.read_text())
    assert resolved["top_module"] == top
    assert resolved["top_module_extraction_strategy"] == "rtl_authoring_yosys_hierarchy"
    assert resolved["top_module_status"] == "resolved_from_rtl_authoring"
    assert resolved["top_module_source"]["method"] == "yosys hierarchy -auto-top"
    assert resolved["no_top_module_in_input"] is True


@pytest.mark.parametrize("consumer", ["native_inputs", "professional_interface", "native_lint", "power_intent"])
def test_fresh_consumers_use_authored_top(authored, consumer, monkeypatch):
    project, path = authored
    # Each consumer starts without another consumer having resolved the field.
    if consumer == "native_inputs":
        from flow_native_adapters import inputs
        _, top, _ = inputs(project, {})
    elif consumer == "professional_interface":
        from professional_tb_gen import _native_top_ports
        top, ports, reason = _native_top_ports(project)
        assert reason is None
        assert {port["name"] for port in ports} == {"a", "z"}
    elif consumer == "native_lint":
        from flow_engine_frontend import native_lint
        result = native_lint(project)
        assert result.status == "PASS", result
        report = json.loads((project / "reports/phase2/lint/native_lint.json").read_text())
        top = report["top"]
        assert report["tools"] and all(tool["ran"] for tool in report["tools"])
    else:
        from flow_power import intent
        from flow_native_adapters import Commands
        observed = []
        def run(self, command, **kwargs):
            observed.append(command)
            return SimpleNamespace(returncode=0)
        monkeypatch.setattr(Commands, "run", run)
        directory = project / "power-intent"
        directory.mkdir()
        intent(project, directory, {})
        assert observed
        command, = observed
        top = command[command.index("--top") + 1]
    assert top == "chip_top"
    resolved = json.loads(path.read_text())
    assert resolved["top_module"] == top
    assert resolved["top_module_source"]["step"] == "RTL authoring"


def test_explicit_missing_module_is_not_silently_replaced(authored):
    project, path = authored
    l9 = json.loads(path.read_text())
    l9.update(top_module="declared_but_missing", no_top_module_in_input=False,
              top_module_extraction_strategy="doc_module_decl_or_heading")
    path.write_text(json.dumps(l9))
    with pytest.raises(FileNotFoundError, match="Declared top module declared_but_missing"):
        resolve_rtl_inputs(project)


def test_unstated_top_refuses_multiple_authored_roots(authored):
    project, path = authored
    (project / "phase2/stage1/rtl/other.v").write_text(
        "module other(input wire a, output wire z); assign z=a; endmodule\n")
    before = path.read_bytes()
    with pytest.raises(FileNotFoundError, match="ambiguous candidate top modules: chip_top, other"):
        resolve_rtl_inputs(project)
    assert path.read_bytes() == before


def test_explicit_plugin_declaration_wins_over_legacy_product(authored):
    project, _ = authored
    declaration = project / "plugin_output/declaration.json"
    declaration.parent.mkdir()
    declaration.write_text(json.dumps({"top_module": "declared_but_missing"}))
    with pytest.raises(FileNotFoundError, match="Declared top module declared_but_missing"):
        resolve_rtl_inputs(project)
