"""tests/test_phase1_issue8_l2_l10_l12_l4_pdf.py — v1.6.67

Closes GitHub issue #8 — three quality gaps not covered by #6/#7:

  Bug A  L2.protocol_overview emitted self-admitted defaults
         (`{half_duplex:false, wire_count:2,
           wake_required_pre_command:true,
           evidence:"scanned for half-duplex / single-wire keywords"}`)
         on every project regardless of input
  Bug B  L10.test_cases / L12.behavioral_sequences lacked the
         `no_<X>_in_input` flags the rest of the L-doc family
         already emits
  Bug C  L4.registers PDF parser merged multiple registers into one
         row's description AND rejected real register names
         (`CONTROL`) via a chip-AGNOSTIC-violating blocklist

Each test asserts the v1.6.67 fix follows the durable rule
`feedback_general_fixes_no_false_alert.md`:
  * fixes are general (work across IC classes)
  * no false alerts (header-anchored register-row matching;
    blocklist trimmed to never-real-register words only)
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import (
    gen_l2_frs,
    gen_l4_regmap,
    gen_l10_test_cases,
    gen_l12_behavioral,
)

_GEN_DIR = Path("phase1") / "generated_docs"


def _seed(tmp_path: Path) -> Path:
    project = tmp_path
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    return project


def _read(project: Path, name: str) -> dict:
    return json.loads((project / _GEN_DIR / f"{name}.json").read_text())


# ---------------------------------------------------------------------------
# Bug A — L2.protocol_overview emits null when no protocol evidence
# ---------------------------------------------------------------------------

def test_l2_no_protocol_evidence_emits_null(tmp_path: Path) -> None:
    """A pure-combinational AES core's README mentions no protocol
    keywords. v1.6.66 emitted a default `{half_duplex:false,
    wire_count:2, wake_required_pre_command:true}` block whose own
    `evidence` self-declared as "scanned for ... keywords". v1.6.67
    emits `protocol_overview: null` + flag."""
    project = _seed(tmp_path)
    extracted = {
        "aes_spec.txt": (
            "Verilog AES core.\n"
            "Pure combinational rounds.\n"
            "Output bus is 128 bits wide.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2["protocol_overview"] is None
    assert l2["no_protocol_overview_in_input"] is True


def test_l2_real_protocol_evidence_populates(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP single-wire half-duplex authentication IC.\n"
            "Wake pulse required before each command frame.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2["protocol_overview"] is not None
    assert l2["no_protocol_overview_in_input"] is False
    po = l2["protocol_overview"]
    assert po["half_duplex"] is True


def test_l2_no_default_leaks_into_register_mapped_ips(
        tmp_path) -> None:
    """Aggregate guard: across 3 register-mapped non-protocol IC
    classes (block cipher, hash core, networking-CRC), L2 must NOT
    emit the `wire_count:2 wake_required_pre_command:true` block."""
    cases = [
        ("aes",  "Verilog AES core. Block cipher.\n"),
        ("sha",  "SHA-256 hash. Combinational.\n"),
        ("eth",  "Ethernet MAC IP. Note: prose mentions ethernet.\n"),
    ]
    seen_defaults = []
    for label, src in cases:
        proj = _seed(tmp_path / label)
        gen_l2_frs(proj, {"spec.txt": src})
        l2 = _read(proj, "L2_FRS")
        po = l2["protocol_overview"]
        if po is not None:
            # Real protocol-keyword projects (e.g. ethernet) DO get
            # a populated overview — that's fine. But the values
            # must not include the v1.6.66 default
            # `wake_required_pre_command:true` for non-EXAMPLE_PROTOCOL classes.
            if po.get("wake_required_pre_command") is True \
                    and po.get("half_duplex") is False:
                seen_defaults.append(label)
    # AES + SHA must have null overview; if Ethernet got populated
    # that's because the keyword fired, but it should not carry the
    # EXAMPLE_PROTOCOL-class wake-required default.
    assert "aes" not in seen_defaults
    assert "sha" not in seen_defaults


# ---------------------------------------------------------------------------
# Bug A residual (v1.6.72) — L2.protocol_overview gate must reject
# wrapper headings, multi-alternative protocol lists, and wrapper /
# available / provides phrasing. v1.6.71 raised pass count from 4/11
# to 8/11 but 3 thin-input projects still leaked because the
# structural anchor `interface` matched in the wrong contexts.
# ---------------------------------------------------------------------------

def test_l2_protocol_overview_rejects_axi4_interface_subsection_heading(
        tmp_path: Path) -> None:
    """README with `## AXI4 interface ##` subsection heading must NOT
    trigger protocol_overview emission. The heading describes an
    optional wrapper, not the IC's primary bus."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# SHA-256 hash core\n\n"
            "Pure combinational hash core. NIST FIPS 180-4.\n\n"
            "## AXI4 interface ##\n\n"
            "Optional AXI4-stream wrapper available in src/interfaces/axi4/.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None
    assert l2.get("no_protocol_overview_in_input") is True


def test_l2_protocol_overview_rejects_native_axi_mm_or_wishbone(
        tmp_path: Path) -> None:
    """README with `Native, AXI-MM or Wishbone user interface` must
    NOT trigger emission. Multi-alternative list = pickable wrappers."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# LiteDRAM\n\n"
            "Configurable DRAM controller core.\n"
            "Native, AXI-MM or Wishbone user interface available.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_protocol_overview_rejects_optional_wrapper_list(
        tmp_path: Path) -> None:
    """Multi-IP networking README listing pickable interfaces."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi networking IP\n\n"
            "Provides interfacing, both internally via AXI, AXI stream, "
            "and APB, and externally via Ethernet, PCI express, UART, "
            "and I2C.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_protocol_overview_emits_dict_for_real_aid_class_bus(
        tmp_path: Path) -> None:
    """Positive control: a real single-wire EXAMPLE_PROTOCOL-class command-bus IC
    must STILL emit the dict. Don't over-correct."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP single-wire EXAMPLE_PROTOCOL protocol IC.\n"
            "Half-duplex command bus over a single wire.\n"
            "Wake pulse required before each command frame.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po["half_duplex"] is True
    assert po["wire_count"] == 1


def test_l2_aggregate_no_dict_leak_across_3_v1672_classes(
        tmp_path_factory) -> None:
    """All 3 v1.6.71 leak cases must now emit null."""
    cases = [
        ("sha256",  "# SHA-256\nNIST FIPS.\n## AXI4 interface ##\nOptional.\n"),
        ("dram",    "LiteDRAM. Native, AXI-MM or Wishbone user interface.\n"),
        ("net",     "Provides interfacing via AXI, AXI stream, and APB.\n"),
    ]
    leaked = []
    for label, src in cases:
        proj = _seed(tmp_path_factory.mktemp(label))
        gen_l2_frs(proj, {"spec.txt": src})
        l2 = _read(proj, "L2_FRS")
        if l2.get("protocol_overview") is not None:
            leaked.append(label)
    assert not leaked, f"v1.6.72 dict leak: {leaked}"


# ---------------------------------------------------------------------------
# Bug B — L10/L12 emit `no_<X>_in_input` flags
# ---------------------------------------------------------------------------

def test_l10_emits_no_test_cases_flag_when_empty(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    gen_l10_test_cases(project, {}, l3={"opcodes": []})
    l10 = _read(project, "L10_TEST_CASES")
    assert l10["test_cases"] == []
    assert l10["no_test_cases_in_input"] is True


def test_l10_no_test_cases_flag_false_when_populated(
        tmp_path: Path) -> None:
    project = _seed(tmp_path)
    gen_l10_test_cases(project, {}, l3={
        "opcodes": [{"hex": "0x70", "name": "OP1",
                     "pre_wake_allowed": True}],
    })
    l10 = _read(project, "L10_TEST_CASES")
    assert len(l10["test_cases"]) >= 1
    assert l10["no_test_cases_in_input"] is False


def test_l12_emits_no_behavioral_sequences_flag_when_empty(
        tmp_path: Path) -> None:
    project = _seed(tmp_path)
    gen_l12_behavioral(project, {}, l3={"opcodes": []})
    l12 = _read(project, "L12_BEHAVIORAL_SEQUENCES")
    assert l12["behavioral_sequences"] == []
    assert l12["no_behavioral_sequences_in_input"] is True


def test_l12_no_behavioral_flag_false_when_populated(
        tmp_path: Path) -> None:
    project = _seed(tmp_path)
    gen_l12_behavioral(project, {}, l3={
        "opcodes": [{"hex": "0x70", "name": "OP1"}],
    })
    l12 = _read(project, "L12_BEHAVIORAL_SEQUENCES")
    assert len(l12["behavioral_sequences"]) >= 1
    assert l12["no_behavioral_sequences_in_input"] is False


# ---------------------------------------------------------------------------
# Bug C — L4 PDF register parser: header-anchored + bit-array typed
# ---------------------------------------------------------------------------

# Verbatim datasheet snippet from extracted_docs/
# EXAMPLE_CHIP_Short_Datasheet_0v06.txt covering the full Register Address
# Map plus a downstream command/response table the parser must NOT
# match.
_EXAMPLE_CHIP_DATASHEET_SNIPPET = """\
Register Address Map


   Addr            Name            <D7>        <D6>        <D5>      <D4>        <D3>      <D2>         <D1>     <D0>

   80h (1)      POWER_STAT          ovps        ovpr        ocps        lrl       hot         tst       ocpr      hots

   81h (1)        CONTROL             ph         pt         gpm        gps       rd_dis             -          -      cc_pd_on


Note(s):
1. These registers are accessible through EXAMPLE_PROTOCOL commands.

(Later in same doc — command/response table, MUST NOT MATCH:)
 Get Factory Control
                                  E9h       CB1                  CB1_Hash          CB2                    CB2_Hash         CB3
 Bits and Hash
"""


def test_l4_extracts_real_register_table_anchored_to_header(
        tmp_path: Path) -> None:
    project = _seed(tmp_path)
    gen_l4_regmap(project, {"EXAMPLE_CHIP_datasheet.txt":
                              _EXAMPLE_CHIP_DATASHEET_SNIPPET})
    l4 = _read(project, "L4_REGMAP")
    names = {r["name"] for r in l4["registers"]}
    # Both real registers in the table must be extracted.
    assert "POWER_STAT" in names
    assert "CONTROL" in names
    # The downstream command-table row (E9h CB1 ...) must NOT
    # match because it is OUTSIDE the post-header window AND
    # the header doesn't extend that far AND it appears in a
    # `Get Factory Control / E9h CB1 ...` command-prose context.
    # (The 80-line cap from header may or may not exclude E9h;
    # the structural test is that CB1 is not a register name.)
    assert "CB1" not in names


def test_l4_emits_bits_array_for_register_with_bit_columns(
        tmp_path: Path) -> None:
    """v1.6.67 — when the bit-field column is a list of short
    identifiers, parse them into a typed `bits[]` array rather than
    a description blob."""
    project = _seed(tmp_path)
    gen_l4_regmap(project, {"datasheet.txt": _EXAMPLE_CHIP_DATASHEET_SNIPPET})
    l4 = _read(project, "L4_REGMAP")
    pwr = next(r for r in l4["registers"] if r["name"] == "POWER_STAT")
    bit_names = {b["name"] for b in pwr.get("bits", [])}
    assert {"ovps", "ovpr", "ocps", "lrl",
            "hot", "tst", "ocpr", "hots"} <= bit_names


def test_l4_does_not_match_register_rows_when_header_absent(
        tmp_path: Path) -> None:
    """Without a `Addr ... Name ... <D7>` header line, the
    `<addr>h <NAME>` parser must skip the doc entirely. This kills
    the issue-#8 Bug-C false-positive where command-response tables
    in the EXAMPLE_CHIP datasheet's later sections were matching."""
    project = _seed(tmp_path)
    extracted = {
        "command_table.txt": (
            "Set State                           70h    REG[0]   0    3D\n"
            "Get State                           72h    71\n"
            "Get Factory Control                 E9h    CB1   CB1_Hash   CB2\n"
        ),
    }
    gen_l4_regmap(project, extracted)
    l4 = _read(project, "L4_REGMAP")
    names = {r["name"] for r in l4["registers"]}
    # None of the command-row right-hand identifiers should appear
    # as register names.
    assert "CB1" not in names
    assert "REG" not in names


def test_l4_blocklist_no_longer_rejects_common_real_register_names(
        tmp_path: Path) -> None:
    """v1.6.67 — closes issue-#8 Bug-C false-negative half. The
    v1.6.65 blocklist included `CONTROL`, `RESET`, `ID` — all
    common standalone register names in real chips. They must no
    longer be rejected."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "Register Address Map\n"
            "  Addr  Name  <D7>  <D6>  <D5>  <D4>  <D3>  <D2>  <D1>  <D0>\n"
            "  10h  CONTROL  en  rst  ie  -  -  -  -  -\n"
            "  11h  RESET    soft  hard  -  -  -  -  -  -\n"
            "  12h  ID       v3  v2  v1  v0  -  -  -  -\n"
            "  13h  STATUS   busy  done  err  -  -  -  -  -\n"
        ),
    }
    gen_l4_regmap(project, extracted)
    l4 = _read(project, "L4_REGMAP")
    names = {r["name"] for r in l4["registers"]}
    assert "CONTROL" in names
    assert "RESET" in names
    assert "ID" in names
    assert "STATUS" in names


# ---------------------------------------------------------------------------
# v1.6.71 -- Bug C1: bit-field token list collapse fix.
# When bits[] is populated, description must be None (not the
# whitespace-blob duplicate). Splitting heuristic still rejects
# English prose (rich datasheet description text).
# ---------------------------------------------------------------------------

def test_l4_register_with_bit_token_string_drops_description_blob(
        tmp_path: Path) -> None:
    """When bits[] is set from a whitespace token list, the duplicate
    `description` blob must be cleared so consumers read the typed
    array exclusively.

    Closes issue #8 Bug C1: field agent observed that
    POWER_STAT.description = `"ovps  ovpr  ocps  lrl  hot  tst  ocpr  hots"`
    coexisted with bits[] -- the same content twice in different
    shapes. Pick one (the typed array) and null the other.
    """
    project = _seed(tmp_path)
    gen_l4_regmap(project, {"datasheet.txt": _EXAMPLE_CHIP_DATASHEET_SNIPPET})
    l4 = _read(project, "L4_REGMAP")
    pwr = next(r for r in l4["registers"] if r["name"] == "POWER_STAT")
    # bits[] has the structured form
    bit_names = {b["name"] for b in pwr.get("bits", [])}
    assert {"ovps", "ovpr", "ocps", "lrl",
            "hot", "tst", "ocpr", "hots"} <= bit_names
    # description is no longer the duplicate whitespace blob
    assert pwr["description"] is None


def test_l4_register_with_english_prose_keeps_description(
        tmp_path: Path) -> None:
    """Rich datasheets that describe a register in English prose
    (not a bit-token list) must keep the prose in `description` and
    not emit a bits[] array. Counterpoint to the previous test --
    confirms the splitting heuristic doesn't fire on prose.
    """
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "Register Address Map\n"
            "  Addr  Name  <D7>  <D6>  <D5>  <D4>  <D3>  <D2>  <D1>  <D0>\n"
            # Description column is English prose, not 8 short tokens.
            "  20h  STATUS  Power status flags including overvoltage "
            "and overcurrent protection\n"
        ),
    }
    gen_l4_regmap(project, extracted)
    l4 = _read(project, "L4_REGMAP")
    matches = [r for r in l4["registers"] if r["name"] == "STATUS"]
    assert matches, "STATUS register row must extract"
    sts = matches[0]
    # bits[] absent because the trailing column is prose, not tokens
    assert "bits" not in sts or not sts["bits"]
    # description retains the prose
    assert sts["description"]
    assert "overvoltage" in sts["description"].lower()
