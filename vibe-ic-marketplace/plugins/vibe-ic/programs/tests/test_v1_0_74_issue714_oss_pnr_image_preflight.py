"""ORGANIC #714 — CVDP scoring preflight must detect the OSS_PNR_IMAGE (synth)
requirement for area-opt (cid007) problems and FAIL CLOSED when it is unset.

DEFECT (CVDP 100% campaign): area-opt problems carry a `Dockerfile.synth` whose
base image is the `__OSS_PNR_IMAGE__` template var (distinct from
`__OSS_SIM_IMAGE__`). If the scoring driver sets only OSS_SIM_IMAGE, OSS_PNR_IMAGE
defaults to the unpullable proprietary image, the synth container never builds,
yosys never runs, and the synth subtest FALSE-FAILS even on correct area-reduced
RTL. 3 cid007 problems flipped to PASS once OSS_PNR_IMAGE was set.

FIX (chip-AGNOSTIC, no-cheating — FAIL CLOSED, never hardcode a magic image):
cvdp_env_preflight scans a problem dir for `__OSS_PNR_IMAGE__`; if present and
OSS_PNR_IMAGE is unset, it REFUSES to score (verdict REFUSE) and reports
`oss_pnr_image_required: true`.

§4.05 NO-LEAK: a problem WITHOUT the template → `oss_pnr_image_required: false`,
no refusal; the existing #536 sim-image-only invocation is unchanged.
"""
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "benchmark"))
import cvdp_env_preflight as E  # noqa: E402


def _area_opt_problem(tmp_path: Path) -> Path:
    """A cid007-shaped problem dir whose synth Dockerfile uses __OSS_PNR_IMAGE__
    (the real defect artifact shape)."""
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "Dockerfile.synth").write_text(
        "FROM __OSS_PNR_IMAGE__\nRUN yosys -V\n")
    (src / "Dockerfile.sim").write_text("FROM __OSS_SIM_IMAGE__\n")
    return tmp_path


def test_acceptance_dockerfile_synth_uses_pnr_template(tmp_path):
    """驗收 (verbatim): the area-opt synth Dockerfile carries __OSS_PNR_IMAGE__."""
    prob = _area_opt_problem(tmp_path)
    s = (prob / "src" / "Dockerfile.synth").read_text()
    assert "__OSS_PNR_IMAGE__" in s
    required, files = E.harness_requires_pnr_image(prob)
    assert required is True
    assert any(f.name == "Dockerfile.synth" for f in files)


def test_end_state_unset_pnr_image_refuses(tmp_path, monkeypatch, capsys):
    """END-STATE: scanning an area-opt problem with OSS_PNR_IMAGE UNSET REFUSES
    (rc=1) and reports the requirement — no silent synth false-fail."""
    prob = _area_opt_problem(tmp_path)
    monkeypatch.delenv("OSS_PNR_IMAGE", raising=False)
    out_json = tmp_path / "verdict.json"
    rc = E.main(["--problem-dir", str(prob), "--json", str(out_json)])
    assert rc == 1
    v = json.loads(out_json.read_text())
    assert v["oss_pnr_image_required"] is True
    assert v["oss_pnr_image_set"] is False
    assert v["verdict"] == "REFUSE"


def test_end_state_set_pnr_image_passes(tmp_path, monkeypatch):
    """With OSS_PNR_IMAGE set + pullable, the PNR requirement is satisfied."""
    prob = _area_opt_problem(tmp_path)
    monkeypatch.setenv("OSS_PNR_IMAGE", "hpretl/iic-osic-tools:latest")
    monkeypatch.setattr(E, "_image_pullable", lambda img, runner=None: True)
    out_json = tmp_path / "verdict.json"
    rc = E.main(["--problem-dir", str(prob), "--json", str(out_json)])
    v = json.loads(out_json.read_text())
    assert v["oss_pnr_image_required"] is True
    assert v["oss_pnr_image_set"] is True
    assert rc == 0 and v["verdict"] == "PASS"


def test_noleak_non_area_opt_problem_not_required(tmp_path, monkeypatch):
    """§4.05: a problem with NO __OSS_PNR_IMAGE__ template → not required, no
    refusal even with OSS_PNR_IMAGE unset."""
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "Dockerfile.sim").write_text("FROM __OSS_SIM_IMAGE__\n")
    monkeypatch.delenv("OSS_PNR_IMAGE", raising=False)
    out_json = tmp_path / "verdict.json"
    rc = E.main(["--problem-dir", str(tmp_path), "--json", str(out_json)])
    v = json.loads(out_json.read_text())
    assert v["oss_pnr_image_required"] is False
    assert rc == 0 and v["verdict"] == "PASS"


def test_noleak_no_args_is_input_error():
    """Passing neither --image nor --problem-dir is an input error (rc=2)."""
    assert E.main([]) == 2


# ── #714 round-2: materialized (post-substitution) gated literal ──────────────

def test_materialized_gated_literal_detected_and_refused(tmp_path, monkeypatch):
    """ROUND-2: after run_benchmark MATERIALIZES the harness, `__OSS_PNR_IMAGE__`
    is already substituted to the gated `nvidia/cvdp-sim:<tag>` literal. The
    preflight must still detect the synth requirement AND refuse — even with
    OSS_PNR_IMAGE set, because THIS dir's container will pull the gated image.
    Field: 16/302 area-opt problems false-failed this way, logged as ~650-byte
    'TRUNCATED'; 9 flipped to PASS once the OSS image was substituted."""
    src = tmp_path / "harness" / "57" / "src"
    src.mkdir(parents=True)
    (src / "Dockerfile.synth").write_text(
        "FROM nvidia/cvdp-sim:v1.0.0 AS BASE\nRUN pip install pytest==8.3.2\n")
    monkeypatch.setenv("OSS_PNR_IMAGE", "cvdp-sim-oss:v110")
    out_json = tmp_path / "verdict.json"
    rc = E.main(["--problem-dir", str(tmp_path), "--json", str(out_json)])
    v = json.loads(out_json.read_text())
    assert v["oss_pnr_image_required"] is True
    assert v["oss_pnr_image_materialized_gated"] is True
    assert rc == 1 and v["verdict"] == "REFUSE"
    assert any("MATERIALIZED gated" in d for d in v["deviations"])


def test_noleak_materialized_oss_image_not_flagged(tmp_path, monkeypatch):
    """§4.05 no-leak: a synth Dockerfile materialized with the OSS image (NOT the
    gated literal) is NOT flagged — the detector keys on the gated repo name, so
    a correctly-substituted OSS harness scores without a false refusal."""
    src = tmp_path / "harness" / "57" / "src"
    src.mkdir(parents=True)
    (src / "Dockerfile.synth").write_text("FROM cvdp-sim-oss:v110 AS BASE\n")
    monkeypatch.delenv("OSS_PNR_IMAGE", raising=False)
    out_json = tmp_path / "verdict.json"
    rc = E.main(["--problem-dir", str(tmp_path), "--json", str(out_json)])
    v = json.loads(out_json.read_text())
    assert v["oss_pnr_image_required"] is False
    assert rc == 0 and v["verdict"] == "PASS"


# ── #714 round-2 Step-2.7 remediations ────────────────────────────────────────

def test_comment_mention_gated_not_flagged(tmp_path, monkeypatch):
    """Step-2.7 (MED): a synth Dockerfile that uses the OSS base but merely NAMES
    the gated image in a `#` comment (e.g. documenting the default it replaced)
    must NOT be flagged — the gated scan is comment-stripped, so a mention is not
    mistaken for the active base."""
    src = tmp_path / "harness" / "57" / "src"
    src.mkdir(parents=True)
    (src / "Dockerfile.synth").write_text(
        "# default base (overridden via OSS_PNR_IMAGE): nvidia/cvdp-sim:v1.0.0\n"
        "FROM cvdp-sim-oss:v110 AS BASE\nRUN yosys -V\n")
    monkeypatch.setenv("OSS_PNR_IMAGE", "cvdp-sim-oss:v110")
    out_json = tmp_path / "verdict.json"
    rc = E.main(["--problem-dir", str(tmp_path), "--json", str(out_json)])
    v = json.loads(out_json.read_text())
    assert v["oss_pnr_image_required"] is False
    assert rc == 0 and v["verdict"] == "PASS"


@pytest.mark.parametrize("from_line", [
    "FROM nvidia/cvdp-sim\n",                                  # tagless → :latest
    "FROM nvidia/cvdp-sim@sha256:" + ("a" * 64) + "\n",        # digest-pinned
    "FROM nvcr.io/nvidia/cvdp-sim:v1.0.0\n",                   # registry-prefixed
])
def test_tagless_and_digest_gated_refused(tmp_path, monkeypatch, from_line):
    """Step-2.7 (false-SKIP): the gated REPO is proprietary regardless of how it
    is referenced — tagless, digest-pinned, or registry-prefixed all need auth
    and `pull access denied`, so each must still REFUSE."""
    src = tmp_path / "harness" / "57" / "src"
    src.mkdir(parents=True)
    (src / "Dockerfile.synth").write_text(from_line + "RUN yosys -V\n")
    monkeypatch.setenv("OSS_PNR_IMAGE", "cvdp-sim-oss:v110")
    out_json = tmp_path / "verdict.json"
    rc = E.main(["--problem-dir", str(tmp_path), "--json", str(out_json)])
    v = json.loads(out_json.read_text())
    assert v["oss_pnr_image_materialized_gated"] is True
    assert rc == 1 and v["verdict"] == "REFUSE"


def test_deviation_offers_only_the_working_remedy(tmp_path, monkeypatch):
    """Step-2.7 (MED): the baked-gated deviation must NOT advertise the
    'retag the OSS image to the gated name' remedy (it never clears this gate and
    defeats OSS reproducibility) — only the re-materialize-with-OSS remedy."""
    src = tmp_path / "harness" / "57" / "src"
    src.mkdir(parents=True)
    (src / "Dockerfile.synth").write_text("FROM nvidia/cvdp-sim:v1.0.0 AS BASE\n")
    monkeypatch.setenv("OSS_PNR_IMAGE", "cvdp-sim-oss:v110")
    out_json = tmp_path / "verdict.json"
    E.main(["--problem-dir", str(tmp_path), "--json", str(out_json)])
    dev = " ".join(json.loads(out_json.read_text())["deviations"])
    assert "retag" not in dev.lower(), "the non-working retag remedy must be gone"
    assert "MATERIALIZE" in dev.upper(), "re-materialize remedy must be present"


def test_noleak_sibling_repo_not_flagged(tmp_path, monkeypatch):
    """§4.05: a sibling repo (`nvidia/cvdp-bench`) or a longer name
    (`nvidia/cvdp-sim-extended`) must NOT match the gated detector."""
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "Dockerfile.synth").write_text(
        "FROM nvidia/cvdp-bench:v1.0.0\nRUN echo nvidia/cvdp-sim-extended:x\n")
    monkeypatch.delenv("OSS_PNR_IMAGE", raising=False)
    out_json = tmp_path / "verdict.json"
    rc = E.main(["--problem-dir", str(tmp_path), "--json", str(out_json)])
    v = json.loads(out_json.read_text())
    assert v["oss_pnr_image_required"] is False
    assert rc == 0 and v["verdict"] == "PASS"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
