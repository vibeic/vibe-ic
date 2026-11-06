"""Native structural observations use operator configuration and tool results."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import rtl_repair_contract as contract


PROMPT = "The implementation shall use only multiplexers for the selectable data path.\n"
RIGHT = "module neutral_select(input a,b,s,output y); assign y=s?b:a; endmodule\n"
WRONG = "module neutral_select(input a,b,s,output y); assign y=(a & ~s)|(b & s); endmodule\n"


def declaration(source):
    quote = PROMPT.strip()
    return {"schema": contract.SCHEMA_STRUCTURAL, "source_path": "neutral_select.sv",
            "source_sha256": contract.sha256_text(WRONG),
            "candidate_sha256": contract.sha256_text(source), "top": "neutral_select",
            "abstraction": contract.STRUCTURAL_ABSTRACTION, "scope": "top_module_cells",
            "requirement_source": {"path": "input/phase1_prompt.md",
                "sha256": contract.sha256_text(PROMPT), "quote": quote,
                "quote_sha256": contract.sha256_text(quote)},
            "expectations": {"required_cell_types": {"$mux": 1},
                "forbidden_cell_types": ["$and", "$or", "$not"], "allow_other_cell_types": False}}


@pytest.fixture
def native(monkeypatch):
    yosys = shutil.which("yosys")
    if not yosys:
        pytest.skip("native Yosys is unavailable")
    original_run, original_which = subprocess.run, shutil.which
    calls = []
    monkeypatch.delenv("VIBEIC_EDA_CONTAINER", raising=False)
    monkeypatch.setenv("VIBEIC_EDA_IMAGE", "operator-selected:local")
    monkeypatch.setattr(shutil, "which", lambda name: "/native-docker" if name == "docker" else original_which(name))

    def run(argv, **kwargs):
        calls.append(list(argv))
        if argv[1:3] == ["image", "inspect"]:
            assert argv[-1] == "{{json .Config.Entrypoint}}"
            return subprocess.CompletedProcess(argv, 0, "null", "")
        if argv[1] == "inspect":
            assert argv[-1] == "operator-runtime" and argv[-2] == "{{.Config.Image}}"
            return subprocess.CompletedProcess(argv, 0, "configured-run:local", "")
        assert argv[1] == "run"
        assert "--pull=never" in argv and "--network=none" in argv
        assert "--read-only" in argv and "--cpus=2" in argv
        assert "--pids-limit=128" in argv
        script = argv[-1]
        mounts = [argv[index + 1] for index, item in enumerate(argv) if item == "-v"]
        for mount in mounts:
            source, destination, _mode = mount.rsplit(":", 2)
            script = script.replace(destination, source)
        return original_run([yosys, "-Q", "-p", script], **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


@pytest.mark.parametrize("source,status", [(RIGHT, "PASS"), (WRONG, "FAIL")])
def test_native_cell_counts_keep_the_original_limits(tmp_path, native, source, status):
    candidate = tmp_path / "candidate.sv"
    candidate.write_text(source)
    spec = declaration(source)
    spec["backend"] = {"kind": "docker", "image": "actor-must-not-select-this",
                       "image_id": "irrelevant-old-identity"}
    result = contract.run_structural_contract(candidate, spec, original_source=WRONG,
        requirement_sources={"input/phase1_prompt.md": PROMPT})
    assert result["verdict"] == status, result
    assert result["execution"]["returncode"] == 0
    assert result["execution"]["image"] == "operator-selected:local"
    assert "image_id" not in result["execution"]
    counts = result["observation"]["cell_type_counts"]
    assert counts.get("$mux", 0) == (1 if status == "PASS" else 0)
    if status == "FAIL":
        assert counts["$and"] == 2 and counts["$or"] == 1 and counts["$not"] == 1
    assert "--memory=4g" in native[-1]


@pytest.mark.parametrize("width,status", [(2, "PASS"), (3, "FAIL")])
def test_native_port_metadata_keeps_declared_widths(tmp_path, native, width, status):
    prompt = "Implement a buffer.\nmodule neutral_ports(input [1:0] a, output [1:0] y);\n"
    source = f"module neutral_ports(input [{width - 1}:0] a, output [1:0] y); assign y=a; endmodule\n"
    facts = contract.prompt_rtl_source_facts(prompt)
    assert facts["kind"] == "HEADER_ONLY"
    candidate = tmp_path / "candidate.sv"
    candidate.write_text(source)
    quote = facts["header"]
    spec = {"schema": contract.SCHEMA_PROMPT_STRUCTURAL,
            "candidate_path": "neutral_ports.sv", "candidate_sha256": contract.sha256_text(source),
            "top": "neutral_ports", "abstraction": contract.STRUCTURAL_ABSTRACTION,
            "scope": "top_module_ports", "prompt_header_preservation": contract.prompt_header_preservation(facts),
            "requirement_source": {"path": "input/phase1_prompt.md", "sha256": contract.sha256_text(prompt),
                "quote": quote, "quote_sha256": contract.sha256_text(quote)},
            "expectations": {"ports_from_prompt_header": True}}
    result = contract.run_structural_contract(candidate, spec, original_source=None,
        requirement_sources={"input/phase1_prompt.md": prompt})
    assert result["verdict"] == status, result
    assert result["observation"]["ports"]["a"]["width"] == width
    assert result["expected_observation"]["ports"]["a"]["width"] == 2
    assert "--memory=2g" in native[-1]


def test_native_yosys_error_is_not_a_structural_pass(tmp_path, native):
    source = "module neutral_select(input a,b,s,output y); assign y=; endmodule\n"
    candidate = tmp_path / "candidate.sv"
    candidate.write_text(source)
    result = contract.run_structural_contract(candidate, declaration(source), original_source=WRONG,
        requirement_sources={"input/phase1_prompt.md": PROMPT})
    assert result["verdict"] == "NOT_MEASURED"
    assert result["execution"]["returncode"] != 0
    assert result["findings"][0]["code"] == "STRUCTURAL_PROOF_EXECUTION_UNMEASURED"


def test_run_container_configuration_selects_image_without_identity(tmp_path, monkeypatch):
    run = tmp_path / "run"
    candidate = run / "candidates/neutral/file.sv"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(RIGHT)
    (run / ".bench_config.json").write_text(json.dumps({"tool_container": "operator-runtime"}))
    monkeypatch.delenv("VIBEIC_EDA_CONTAINER", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: "/native-docker")
    def inspect(argv, **_kwargs):
        assert argv == ["/native-docker", "inspect", "--format", "{{.Config.Image}}", "operator-runtime"]
        return subprocess.CompletedProcess(argv, 0, "selected-native:tag\n", "")
    monkeypatch.setattr(subprocess, "run", inspect)
    assert contract._structural_image(candidate, 10) == ("selected-native:tag", None)


def test_normal_repair_keeps_runtime_configuration_for_detached_candidate(tmp_path, native):
    run = tmp_path / "run"
    project = run / "projects/neutral"
    project.mkdir(parents=True)
    (run / ".bench_config.json").write_text(json.dumps({"tool_container": "operator-runtime"}))
    candidate = tmp_path / "detached/candidate.sv"
    candidate.parent.mkdir()
    candidate.write_text(RIGHT)
    result = contract.validate_normal_repair_contract(
        {"neutral_select.sv": WRONG}, {"neutral_select.sv": RIGHT},
        {"structural": declaration(RIGHT)}, candidate_path=candidate, original_source=WRONG,
        top="neutral_select", requirement_sources={"input/phase1_prompt.md": PROMPT}, runtime_root=project)
    assert result["verdict"] == "PASS", result
    measured = result["structural"]
    assert measured["execution"]["image"] == "configured-run:local"
    assert measured["observation"]["cell_type_counts"] == {"$mux": 1}


def test_missing_native_runtime_does_not_become_a_structural_pass(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate.sv"
    candidate.write_text(RIGHT)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    result = contract.run_structural_contract(candidate, declaration(RIGHT), original_source=WRONG,
        requirement_sources={"input/phase1_prompt.md": PROMPT})
    assert result["verdict"] == "NOT_MEASURED"
    assert result["findings"][0]["code"] == "STRUCTURAL_TOOL_UNAVAILABLE"
