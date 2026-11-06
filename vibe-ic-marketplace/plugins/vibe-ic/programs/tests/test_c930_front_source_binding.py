"""FRONT-I1: current source obligations require a current native JSON binding.

Native execution is substituted only at subprocess.run with checked-in Yosys
output. Production discovery, fingerprinting, publication, and the actual
Step-3 CLI consumers execute; no Docker/EDA/native rerun is claimed.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _cdc_netlist as cn
import test_t91_step3_cdc_netlist_front_end as fixtures


def _fresh(tmp_path):
    return fixtures._project(tmp_path, "fresh", fixtures.FIX / "clean_sync.v",
                             None, fixtures.FIX / "clean_sync.json")




def _rules(result):
    return {row.rule for row in result.findings if row.severity == "ERROR"}


@pytest.mark.parametrize("failure", ["native-failed"])
def test_unsuccessful_producer_cannot_leave_prior_admission(tmp_path, monkeypatch, failure):
    project = _fresh(tmp_path)
    source = project / "phase2/stage1/rtl/clean_sync.v"

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "captured native failure\n")

    monkeypatch.setattr(cn.shutil, "which", lambda _tool: "/captured/yosys")
    monkeypatch.setattr(cn.subprocess, "run", run)
    expected = "CDC_NETLIST_BUILD_FAILED"
    with pytest.raises(cn.Refusal, match=expected):
        cn.build(project, [source], "clean_sync")
    assert not (project / cn.NETLIST_REL).exists()
