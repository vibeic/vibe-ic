"""#513 — the pdk_target extractor gains a SECOND evidence source.

#451 built the extractor and #457 hardened it; both gave it exactly one
source of evidence: PROSE. A design that does not DESCRIBE its process
still STAGES one — liberty / LEF / tech files under its own
`input/pdk*/` tree — and `l19_pdk_floorplan_contract_check` L19-3 fails
precisely on "stages a PDK enablement, declares no target".

What this file pins:

  A. the staged path IS read, and the identifier comes from the SAME
     token table (`_OPEN_PDK_TOKEN_RE`) the prose path uses;
  B. PROSE STILL WINS. The staged source is consulted only after both
     prose passes fall through, so no prose verdict can move. This is
     the whole regression surface of #513: a change that let a staged
     directory override or loosen #457's negation / dual-evidence
     guards would trade a silent null for a silent WRONG value;
  C. a design that stages NOTHING keeps its honest null — no default,
     no fallback, no inference from a flow argument;
  D. provenance survives into a schema-valid `extraction_evidence`
     naming the staged file (a staged match has no line — the PATH is
     the evidence — so the label carries the file instead);
  E. a staged read that yields nothing is DISCLOSED in a sidecar
     outside `generated_docs/`, and that sidecar is NOT reachable by
     the gate's traceability corpus (writing it where L19-2 greps
     would make any target self-traceable — the false-certificate
     shape #512 removed);
  F. `power_budget_uw` / `floorplan_hints` stay ungated and untouched.

Chip-AGNOSTIC: the plugin source keys on directory shape and file
SUFFIX only. PDK identifiers appear here as test fixtures (allowlisted
under `programs/tests/`), and the fixtures deliberately include tokens
no corpus design stages, to prove an unseen PDK behaves identically.
"""
import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import l19_pdk_floorplan_contract_check as GATE     # noqa: E402
import phase1_doc_one_shot_runner as P1             # noqa: E402


def _docs(project: Path, text: str, fname: str = "spec.md") -> Path:
    d = project / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(text)
    return project


def _stage(project: Path, *rel_paths: str) -> Path:
    for rel in rel_paths:
        f = project / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("* staged enablement stub\n")
    return project


def _emit(project: Path):
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        P1._emit_l19_to_l23_skeletons(project)
    return buf.getvalue()


def _l19(project: Path) -> dict:
    return json.loads(
        (P1._pl.generated_docs_dir(project) / "L19_CONSTRAINTS_PDK.json")
        .read_text())


def _gate(project: Path):
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = GATE.main([str(project)])
    except SystemExit as e:                       # pragma: no cover
        rc = int(e.code or 0)
    return rc, buf.getvalue()


# ── A. the staged path is an evidence source of the SAME extractor ─────────

def test_staged_enablement_yields_target_when_prose_is_silent(tmp_path):
    """The #513 acceptance shape: docs that never name a process, and a
    staged PDK enablement that does."""
    p = _docs(tmp_path, "# Core\nA 32-bit integer core. No process named.\n")
    _stage(p, "input/pdk/liberty/sky130_fd_sc_hd__tt_025C_1v80.lib")
    tok, snip, src, line = P1._extract_pdk_target_with_provenance(p)
    assert tok == "sky130"
    assert src == "input/pdk/liberty/sky130_fd_sc_hd__tt_025C_1v80.lib"
    assert snip == src            # the PATH is the evidence
    assert line is None           # ...and it has no line in the prose sense


def test_staged_source_works_with_no_input_docs_at_all(tmp_path):
    """A project may stage a PDK and ship no prose. The pre-#513 early
    return on an empty doc set skipped the staged read entirely."""
    _stage(tmp_path, "input/pdk/lef/gf180mcuD_sc.tlef")
    tok, _snip, src, line = P1._extract_pdk_target_with_provenance(tmp_path)
    assert tok == "gf180mcud"
    assert src == "input/pdk/lef/gf180mcuD_sc.tlef"
    assert line is None


def test_unseen_pdk_behaves_identically(tmp_path):
    """Chip-AGNOSTIC: an identifier no corpus design stages is read the
    same way — nothing is keyed to a design, vendor or filename."""
    p = _docs(tmp_path, "# Block\nnothing about a process here\n")
    _stage(p, "input/pdk/lib/freepdk45_stdcells.lib")
    assert P1._extract_pdk_target_with_provenance(p)[0] == "freepdk45"


def test_staged_root_name_may_carry_the_identifier(tmp_path):
    """The identifier may sit in the staged ROOT's own name rather than
    the leaf filename — the whole relative path is the evidence text."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, "input/pdk_asap7/lib/stdcells.lib")
    assert P1._extract_pdk_target_with_provenance(p)[0] == "asap7"


def test_ihp_prefix_normalised_the_same_way_as_prose(tmp_path):
    """The staged tier reuses the prose tier's token normalisation."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, "input/pdk/ihp-sg13g2/stdcell.lib")
    assert P1._extract_pdk_target_with_provenance(p)[0] == "sg13g2"


def test_two_tuple_shim_still_covers_the_staged_source(tmp_path):
    """`_extract_pdk_target_from_inputs` is the stable public 2-tuple."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, "input/pdk/liberty/sky130_fd_sc_hd__tt_025C_1v80.lib")
    tok, snip = P1._extract_pdk_target_from_inputs(p)
    assert tok == "sky130"
    assert snip.endswith(".lib")


def test_only_enablement_suffixes_are_read(tmp_path):
    """A README parked under `input/pdk/` is not a PDK enablement. The
    gate blocks on `.lib`/`.lef`/`.tlef`/`.tech`/`.db`/`.gds`; the
    extractor must read exactly that population and no wider one."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, "input/pdk/notes/sky130_download_instructions.md")
    assert P1._extract_pdk_target_with_provenance(p)[0] is None


def test_first_staged_file_in_sorted_order_wins(tmp_path):
    """Deterministic: repeated runs pick the same evidence file."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p,
           "input/pdk/liberty/sky130_fd_sc_hd__ss_100C_1v60.lib",
           "input/pdk/liberty/sky130_fd_sc_hd__ff_n40C_1v95.lib",
           "input/pdk/liberty/sky130_fd_sc_hd__tt_025C_1v80.lib")
    first = P1._extract_pdk_target_with_provenance(p)
    assert first[2] == "input/pdk/liberty/sky130_fd_sc_hd__ff_n40C_1v95.lib"
    assert P1._extract_pdk_target_with_provenance(p) == first


# ── B. PROSE WINS — the #513 regression surface ────────────────────────────

def test_prose_wins_over_a_divergent_staged_enablement(tmp_path):
    """When the docs name a process, that answer is returned unchanged
    even though a DIFFERENT PDK is staged beside it. The staged source
    is a fallback, never an override."""
    p = _docs(tmp_path, "Implemented on sky130A with the HD cells.\n")
    _stage(p, "input/pdk/lib/asap7_stdcells.lib")
    tok, _snip, src, line = P1._extract_pdk_target_with_provenance(p)
    assert tok == "sky130a"                 # prose token, not `asap7`
    assert src.endswith("spec.md") and line == 1


def test_457_negation_guard_is_not_bypassed_by_a_staged_directory(tmp_path):
    """#457 residual 1 must hold with a staged tree present: a NEGATED
    commercial-foundry mention still yields nothing, and the staged tree
    must not become a back door that resurrects it."""
    p = _docs(
        tmp_path,
        "Earlier silicon was fabbed at TSMC but not as a 180nm process "
        "target.\n")
    _stage(p, "input/pdk/lib/vendor_stdcells.lib")   # no derivable token
    assert P1._extract_pdk_target_with_provenance(p)[0] is None


def test_457_dual_evidence_guard_applies_to_the_staged_tier_too(tmp_path):
    """A commercial-foundry name in a staged PATH with no numeric
    process node is refused, exactly as it is in prose."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, "input/pdk/smic/stdcells.lib")
    assert P1._extract_pdk_target_with_provenance(p)[0] is None


# ── C. a design that stages nothing keeps its honest null ──────────────────

def test_no_staged_tree_and_no_prose_stays_null(tmp_path):
    p = _docs(tmp_path, "# Adder\nA 32-bit ripple-carry adder.\n")
    assert P1._extract_pdk_target_with_provenance(p) == (None, None, None, None)


def test_an_unrelated_input_directory_is_not_a_staged_pdk(tmp_path):
    """Only `input/pdk*` is a staged-PDK root. A liberty file parked
    somewhere else in the input tree is not an enablement the design
    staged as its PDK."""
    p = _docs(tmp_path, "# Block\nno process named\n")
    _stage(p, "input/macros/liberty/sky130_fd_sc_hd__tt_025C_1v80.lib")
    assert P1._extract_pdk_target_with_provenance(p)[0] is None


# ── D. provenance survives into L19 in schema-valid shape ─────────────────

def test_l19_carries_the_staged_file_as_its_evidence(tmp_path):
    p = _docs(tmp_path, "# Core\nA 32-bit integer core.\n")
    staged = "input/pdk/liberty/sky130_fd_sc_hd__tt_025C_1v80.lib"
    _stage(p, staged)
    _emit(p)
    l19 = _l19(p)
    assert l19["fields"]["pdk_target"] == "sky130"
    ev = l19.get("extraction_evidence")
    assert isinstance(ev, dict) and ev
    # schema-valid shape: {source: [{literal, label}]}
    src_key, entries = next(iter(ev.items()))
    assert src_key == staged
    assert isinstance(entries, list) and entries
    entry0 = entries[0]
    assert isinstance(entry0, dict) and isinstance(entry0.get("literal"), str)
    # a reader must be able to see WHICH staged file produced the value
    assert "pdk_target" in entry0["label"]
    assert staged in entry0["label"]


def test_prose_evidence_label_still_carries_file_and_line(tmp_path):
    """#457 residual 2 regression: the prose label shape is untouched."""
    p = _docs(tmp_path,
              "# Spec\nLine two\nImplemented on sky130A with the HD cells.\n")
    _stage(p, "input/pdk/lib/asap7_stdcells.lib")
    _emit(p)
    l19 = _l19(p)
    assert l19["fields"]["pdk_target"] == "sky130a"
    _src, entries = next(iter(l19["extraction_evidence"].items()))
    assert entries[0]["label"].endswith(":3)")


# ── D'. the gate clears for the RIGHT reason ──────────────────────────────

def test_gate_l19_3_clears_and_the_value_traces_to_the_staged_file(tmp_path):
    p = _docs(tmp_path, "# Core\nA 32-bit integer core.\n")
    _stage(p, "input/pdk/liberty/sky130_fd_sc_hd__tt_025C_1v80.lib")
    _emit(p)
    rc, out = _gate(p)
    assert rc == 0, out
    report = tmp_path / "gate.json"
    GATE.main([str(p), "--json", str(report)])
    rep = json.loads(report.read_text())
    assert rep["verdict"] == "PASS"
    assert rep["pdk_target"] == "sky130"
    assert rep["staged_pdk_enablement"]           # L19-3 population
    assert rep["pdk_target_traceable_in_corpus"] is True
    assert not rep["findings"]


def test_gate_verdict_unchanged_for_a_design_that_stages_nothing(tmp_path):
    """The 191-must-stay-null half: emit changes nothing for a design
    with no staged tree, and the gate's verdict is untouched."""
    p = _docs(tmp_path, "# Adder\nA 32-bit ripple-carry adder.\n")
    _emit(p)
    assert _l19(p).get("fields", {}).get("pdk_target") in (None, "")
    rc, out = _gate(p)
    assert rc == 0, out          # no target declared AND nothing staged
    assert "L19-3" not in out


# ── E. the rejected read is disclosed, and disclosed SAFELY ───────────────

def test_a_staged_read_that_yields_nothing_is_disclosed(tmp_path):
    p = _docs(tmp_path, "# Core\nA 32-bit integer core.\n")
    _stage(p, "input/pdk/lib/vendor_stdcells.lib")
    log = _emit(p)
    assert _l19(p).get("fields", {}).get("pdk_target") in (None, "")
    assert "staged PDK enablement read but no identifier" in log
    side = p / "phase1" / P1.PDK_STAGING_READ_FILENAME
    assert side.is_file()
    rec = json.loads(side.read_text())
    assert rec["staged_pdk_roots"] == ["input/pdk"]
    assert rec["enablement_files"] == ["input/pdk/lib/vendor_stdcells.lib"]
    assert rec["staged_identifier"] is None
    assert rec["adopted_pdk_target"] is None
    assert rec["reason"]
    # mirrored where the audit tooling looks (the #512 dual-write shape)
    assert (p / "reports/phase1" / P1.PDK_STAGING_READ_FILENAME).is_file()


def test_disclosure_records_a_staged_read_that_prose_overrode(tmp_path):
    """Prose winning is not a reason to stay silent about what was
    staged: the divergence is exactly what the foundry pack cares about."""
    p = _docs(tmp_path, "Implemented on sky130A with the HD cells.\n")
    _stage(p, "input/pdk/lib/asap7_stdcells.lib")
    _emit(p)
    rec = json.loads(
        (p / "phase1" / P1.PDK_STAGING_READ_FILENAME).read_text())
    assert rec["staged_identifier"] == "asap7"
    assert rec["adopted_pdk_target"] == "sky130a"
    assert rec["adopted_evidence_kind"] == "input_doc_prose"


def test_no_staged_root_writes_no_disclosure(tmp_path):
    """No read was attempted, so there is nothing to disclose. A record
    of a read that never happened is noise, not honesty."""
    p = _docs(tmp_path, "# Adder\nA 32-bit ripple-carry adder.\n")
    _emit(p)
    assert not (p / "phase1" / P1.PDK_STAGING_READ_FILENAME).exists()
    assert not (p / "reports/phase1" / P1.PDK_STAGING_READ_FILENAME).exists()


def test_disclosure_is_not_reachable_by_the_gate_traceability_corpus(tmp_path):
    """FALSE-CERTIFICATE GUARD. The sidecar names the identifier it
    read. If it were written anywhere `_design_input_corpus` scans,
    L19-2 would grep it and pronounce ANY declared target traceable to
    the design's own inputs. Pin that it cannot: a target that appears
    ONLY in the sidecar still FAILS L19-2."""
    p = _docs(tmp_path, "# Core\nA 32-bit integer core.\n")
    _stage(p, "input/pdk/lib/vendor_stdcells.lib")
    _emit(p)
    side = p / "phase1" / P1.PDK_STAGING_READ_FILENAME
    assert side.is_file()
    # plant the token in the sidecar (both copies) and nowhere else
    planted = "zzq7pdk"
    for d in ("phase1", "reports/phase1"):
        f = p / d / P1.PDK_STAGING_READ_FILENAME
        f.write_text(f.read_text().replace('"staged_identifier": null',
                                           f'"staged_identifier": "{planted}"'))
    assert planted in side.read_text()
    l19_path = (P1._pl.generated_docs_dir(p) / "L19_CONSTRAINTS_PDK.json")
    doc = json.loads(l19_path.read_text())
    doc.setdefault("fields", {})["pdk_target"] = planted
    l19_path.write_text(json.dumps(doc))
    rc, out = _gate(p)
    assert rc == 1, out
    assert "L19-2" in out


# ── F. the deliberately ungated neighbours stay ungated ──────────────────

def test_power_budget_and_floorplan_hints_are_untouched(tmp_path):
    """`l19_pdk_floorplan_contract_check` declines to gate these two and
    says so. Populating pdk_target must not quietly extend the gating."""
    p = _docs(tmp_path, "# Core\nA 32-bit integer core.\n")
    _stage(p, "input/pdk/liberty/sky130_fd_sc_hd__tt_025C_1v80.lib")
    _emit(p)
    fields = _l19(p)["fields"]
    assert fields.get("power_budget_uw") in (None, "")
    assert not fields.get("floorplan_hints")
    rc, out = _gate(p)
    assert rc == 0, out
    assert "power_budget_uw is unset" in out
    assert "floorplan_hints is empty" in out
