#!/usr/bin/env python3
"""_cdc_netlist.py — the step-3 CDC/RDC rules over a Yosys JSON netlist.

Review row 3 (70-step migration, lane mig-rtlver): no CDC/RDC engine exists in
the image (Verilator 5.053 rejects `--cdc`; no LibreLane step, no OpenROAD
command), so the rules stay ours. What moves is their INPUT. The regex front
ends in `cdc_async_input_check`, `clock_domain_reg_crossing_check` and
`reset_dependency_check` re-derive from RTL text what a netlist states: which
flop is clocked by which net, which net resets it (async or sync), what feeds
its D pin, and which names are top-level ports. A spelling decided a verdict
there (#2063: an internal `b_raw` wire read as an async input port); here
port-ness, clock and reset are structural facts.

FRONT END. The netlist is exactly what LibreLane's `Yosys.JsonHeader` writes
(librelane/scripts/pyosys/json_header.py in vibeic-eda 0.3.77):

    hierarchy -check -top <T> -nokeep_prints -nokeep_asserts
    rename -top <T>; proc; flatten; opt_clean -purge; json -o <out>

`build()` runs those passes (local yosys, else the image
`librelane_contract.resolve_image` answers), retains their raw JSON, then runs
native constant normalization in a fresh invocation of the same engine. The
explicit second step folds binary constant expressions without optimizing flop
types or clock inversions. Both invocations and artifacts bind the CDC input;
this extension is not a claim about LibreLane's own JsonHeader pass list.
`load()` accepts either the normalized output or a LibreLane
`Yosys.JsonHeader` `json_h` file. After `proc` without `opt_dff`, a sync
reset is the outermost `$mux` in front of D with a constant arm, an enable is
a `$mux` whose other arm is the flop's own Q, and an async reset is the `ARST`
pin of `$adff` or the constant-valued `ALOAD` of `$aldff`.

SystemVerilog source uses the native Slang reader in one compilation unit,
with the existing package/import ordering before elaboration. Plain Verilog
keeps the legacy reader. Both preserve the CDC producer's default SYNTHESIS
define, and the actual frontend/read order remain part of the native binding.

The step switch (`librelane_contract.selected_mode(project, "3")`):
  direct    — regex front ends only (explicit opt-out)
  librelane — the netlist rules decide; a missing netlist refuses (no fallback)
  dual      — both run; findings are the union and every disagreement between
              the two front ends is reported by name.

chip-AGNOSTIC: nothing here names a design, PDK, cell or vendor. The only
names consulted are yosys's own internal cell types.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Where the runner writes the netlist and where the gates read it.
NETLIST_REL = "reports/phase2/cdc/netlist.json"
NETLIST_LOG_REL = "reports/phase2/cdc/netlist.yosys.log"
NETLIST_MANIFEST_REL = "reports/phase2/cdc/netlist_front_end.json"
NETLIST_RAW_REL = "reports/phase2/cdc/netlist.raw.json"
NETLIST_NORMALIZE_LOG_REL = "reports/phase2/cdc/netlist.normalize.yosys.log"

#: `librelane/scripts/pyosys/json_header.py` after reading the sources.
JSON_HEADER_PASSES = (
    "hierarchy -check -top {top} -nokeep_prints -nokeep_asserts",
    "rename -top {top}",
    "proc",
    "flatten",
    "opt_clean -purge",
)

# A fresh native read is intentional: the active Slang design does not fold
# every constant expression in-place. Preserve unknowns and native clock edges;
# in particular do not use opt_dff, -full or -undriven here.
CONSTANT_NORMALIZATION_PASSES = ("opt_expr -keepdc -noclkinv", "opt_clean -purge")

FLOP_TYPES = {"$dff", "$adff", "$dffe", "$adffe", "$sdff", "$sdffe",
              "$sdffce", "$dffsr", "$dffsre", "$aldff", "$aldffe"}
_INTERNAL_ADFF_RE = re.compile(r"^\$_DFF_([NP])([NP])([01])_$")
_INTERNAL_DFF_RE = re.compile(r"^\$_DFF_([NP])_$")
#: Single-input cells a clock or reset may pass through and stay the same net.
_TRANSPARENT = {"$buf", "$pos", "$not", "$_BUF_", "$_NOT_"}
_MEMORY = {"$mem", "$mem_v2", "$memrd", "$memrd_v2"}
_OUTPUT_PORTS = {"Y", "Q", "RD_DATA", "DATA"}


class Refusal(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def _is_flop_type(cell_type: str) -> bool:
    return (cell_type in FLOP_TYPES
            or _INTERNAL_ADFF_RE.fullmatch(cell_type) is not None
            or _INTERNAL_DFF_RE.fullmatch(cell_type) is not None)


def gate_mode(project: Path) -> str:
    """The step-3 front-end mode from the project's step switch."""
    import librelane_contract
    return librelane_contract.selected_mode(Path(project), "3")


# ─────────────────────────────── front end ────────────────────────────────

def _uses_slang(files: List[Path], sv: bool = True) -> bool:
    return sv and any(Path(f).suffix == ".sv" for f in files)


def _read_order(files: List[Path], sv: bool = True) -> List[Path]:
    if _uses_slang(files, sv):
        from rtl_transitive_cone import topological_package_first
        return topological_package_first(list(files))
    return list(files)


def yosys_script(files: List[Path], top: Optional[str], out: Path,
                 sv: bool = True) -> str:
    if _uses_slang(files, sv):
        files = _read_order(files, sv)
        if any(any(c.isspace() or c in ';"\\' for c in str(f)) for f in files):
            raise Refusal("CDC_NETLIST_UNSUPPORTED_PATH",
                          "read_slang cannot represent the selected source path token")
        reads = ["read_slang --single-unit " + (f"--top {top} " if top else "")
                 + " ".join(map(str, files))]
    else:
        reads = [f"read_verilog {'-sv ' if sv else ''}-defer {f}" for f in files]
    passes = list(JSON_HEADER_PASSES)
    if top:
        passes = [p.format(top=top) for p in passes]
    else:
        passes = ["hierarchy -check -auto-top -nokeep_prints -nokeep_asserts"
                  ] + passes[2:]
    return "; ".join(reads + passes + [f"json -o {out}"])


def normalization_script(raw: Path, out: Path) -> str:
    """Native JSON constant folding, in a separate invocation of the producer."""
    return "; ".join([f"read_json {raw}", *CONSTANT_NORMALIZATION_PASSES,
                      f"json -o {out}"])


def source_binding(project: Path, top: Optional[str],
                   rtl_files: Optional[List[Path]] = None, *,
                   normalization: bool = True) -> dict:
    """Current native frontend inputs, using the existing source/hash contracts.

    Headers and structured top/switch declarations are dependencies too. A
    partial read cannot establish a verdict over the current source population.
    Include dependencies use the existing resolver; the Yosys frontend remains
    the connectivity producer. Only the reader of a proven one-stage checkpoint
    uses the original options/fingerprint without normalization.
    """
    import _specrtl_common as sources
    from _chip_synth_read import NON_SILICON_SUBSTRS
    from _step_identity import resolved_inputs_digest
    import librelane_contract as ll
    from p0_tool_frontend_check import _top
    from formal_property_run import resolve_include_headers
    project = Path(project).resolve()
    files = [p.resolve() for p in sources.rtl_source_files(project)
             if not any(t in p.name.lower() for t in NON_SILICON_SUBSTRS)]
    if not files:
        raise Refusal("CDC_NETLIST_NO_RTL", "no current RTL source population")
    if rtl_files is not None and set(map(Path.resolve, rtl_files)) != set(files):
        raise Refusal("CDC_NETLIST_PARTIAL_SOURCES",
                      "native read must cover the current RTL source population")
    declared = _top(project)
    if declared and top and declared != top:
        raise Refusal("CDC_NETLIST_TOP_MISMATCH",
                      f"declared top {declared!r}, native requested top {top!r}")
    deps = set(files)
    deps.update(p.resolve() for p in sources.rtl_source_files(
        project, exts=("*.vh", "*.svh")))
    # Explicit includes remain inputs even when they live outside the canonical
    # tree. Reuse the existing resolver rather than widening the header census.
    deps.update(p.resolve() for p in resolve_include_headers(files, [project]))
    for rel in ("phase1/generated_docs/L9_INTEGRATION_SPEC.json",
                "phase1/generated_docs/L9_INTEGRATION.json",
                "phase3/librelane_switch.json"):
        if (project / rel).is_file():
            deps.add(project / rel)
    options = {"sv": True,
               "frontend": "read_slang" if _uses_slang(files) else "read_verilog",
               "passes": list(JSON_HEADER_PASSES),
               "requested_top": top, "declared_top": declared}
    if normalization:
        options["normalization"] = {"frontend": "read_json",
                                    "passes": list(CONSTANT_NORMALIZATION_PASSES)}
    inputs = [("source", p, "raw") for p in sorted(deps)]
    fingerprint, why = resolved_inputs_digest(
        project, inputs, {"frontend_options": json.dumps(options, sort_keys=True)})
    if fingerprint is None:
        raise Refusal("CDC_NETLIST_SOURCE_UNREADABLE", "; ".join(why))
    return {"fingerprint": fingerprint, "options": options,
            "rtl_files": [os.path.relpath(p, project) for p in sorted(files)],
            "files": [{"path": os.path.relpath(p, project), "sha256": ll.digest(p)}
                      for p in sorted(deps)]}


def require_binding(project: Path, path: Path, nl: "Netlist") -> dict:
    """Require the existing producer manifest to bind this JSON to current inputs."""
    import librelane_contract as ll
    manifest = path.parent / Path(NETLIST_MANIFEST_REL).name
    try:
        rec = ll._load(manifest)
        inputs = rec.get("input")
        producer = rec.get("producer")
        if not isinstance(inputs, dict) or not isinstance(producer, dict):
            raise ValueError("missing native input/producer binding")
        top = inputs["options"]["requested_top"]
        if top is not None and (not isinstance(top, str) or top != nl.top):
            raise Refusal("CDC_NETLIST_TOP_MISMATCH", "native top differs from JSON top")
        if (producer.get("step") != "Yosys.JsonHeader"
                or type(producer.get("exit_code")) is not int
                or producer["exit_code"] != 0
                or not isinstance(producer.get("argv"), list) or not producer["argv"]
                or rec.get("top") != nl.top):
            raise ValueError("missing successful native producer run/top")
        root = Path(producer["source_root"])
        order = producer["read_order"]
        if not root.is_absolute() or not isinstance(order, list):
            raise ValueError("missing native source root/read order")
        files = [Path(os.path.normpath(root / rel)) for rel in order]
        argv = producer["argv"]
        hashes = rec.get("sha256") or {}
        # Published one-stage checkpoints have a final-output invocation and
        # the original input fingerprint. Absence of new fields alone cannot
        # downgrade a raw-output invocation or a partial normalization claim.
        legacy = ("normalization" not in inputs["options"]
                  and "normalization" not in producer
                  and "netlist.raw.json" not in hashes
                  and "netlist.normalize.yosys.log" not in hashes
                  and argv[-3:] == ["-q", "-p", yosys_script(
                      files, top, root / Path(NETLIST_REL).with_suffix(".json.tmp"))])
        current = source_binding(project, top, normalization=not legacy)
        declared = current["options"]["declared_top"]
        if declared and declared != nl.top:
            raise Refusal("CDC_NETLIST_TOP_MISMATCH", "current declared top differs from JSON top")
        if current != inputs:
            raise Refusal("CDC_NETLIST_STALE", "source population, contents, top or options changed")
        if sorted(order) != current["rtl_files"]:
            raise ValueError("native command read a partial/different source population")
        raw = root / NETLIST_RAW_REL
        output = root / NETLIST_REL if legacy else raw
        script = yosys_script(files, top, output.with_suffix(".json.tmp"))
        if argv[-3:] != ["-q", "-p", script] or not (
                argv[0] == "yosys" or
                any(argv[i:i + 2] == ["--entrypoint", "yosys"]
                    for i in range(len(argv) - 1))):
            raise ValueError("native invocation does not match frontend sources/top/options")
        normalization = producer.get("normalization")
        if not legacy and (not isinstance(normalization, dict)
                or type(normalization.get("exit_code")) is not int
                or normalization["exit_code"] != 0
                or normalization.get("argv") != argv[:-3] + [
                    "-q", "-p", normalization_script(
                        raw, root / Path(NETLIST_REL).with_suffix(".json.tmp"))]):
            raise ValueError("missing successful normalization by the same native engine")
        log = path.parent / Path(NETLIST_LOG_REL).name
        raw = path.parent / Path(NETLIST_RAW_REL).name
        normalize_log = path.parent / Path(NETLIST_NORMALIZE_LOG_REL).name
        if (hashes.get("netlist.json") != ll.digest(path)
                or hashes.get("netlist.yosys.log") != ll.digest(log)):
            raise Refusal("CDC_NETLIST_STALE", "native output or invocation log hash changed")
        if not legacy and (
                hashes.get("netlist.raw.json") != ll.digest(raw)
                or normalization.get("input_sha256") != ll.digest(raw)
                or hashes.get("netlist.normalize.yosys.log") != ll.digest(normalize_log)):
            raise Refusal("CDC_NETLIST_STALE", "native output or invocation log hash changed")
        if not log.read_text().startswith("$ " + " ".join(argv) + "\n"):
            raise ValueError("invocation transcript does not record this native command")
        if not legacy and not normalize_log.read_text().startswith(
                "$ " + " ".join(normalization["argv"]) + "\n"):
            raise ValueError("normalization transcript does not record this native command")
    except Refusal:
        raise
    except (OSError, ValueError, KeyError, TypeError, ll.Refusal) as exc:
        raise Refusal("CDC_NETLIST_UNBOUND",
                      f"no complete current native producer binding: {exc}") from None
    return rec


def build(project: Path, rtl_files: List[Path], top: Optional[str],
          image: Optional[str] = None, docker: str = "docker") -> Path:
    """Write a bound raw JsonHeader and its native constant-normalized CDC input."""
    project = Path(project).resolve()
    out = project / NETLIST_REL
    log = project / NETLIST_LOG_REL
    manifest = project / NETLIST_MANIFEST_REL
    raw = project / NETLIST_RAW_REL
    normalize_log = project / NETLIST_NORMALIZE_LOG_REL
    # No failed, partial or interrupted producer can leave a prior admission.
    manifest.unlink(missing_ok=True)
    out.unlink(missing_ok=True)
    raw.unlink(missing_ok=True)
    normalize_log.unlink(missing_ok=True)
    binding = source_binding(project, top, rtl_files)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.unlink(missing_ok=True)
    raw_tmp = raw.with_suffix(".json.tmp")
    raw_tmp.unlink(missing_ok=True)
    files = _read_order([Path(f).resolve() for f in rtl_files])
    script = yosys_script(files, top, raw_tmp)
    if shutil.which("yosys"):
        argv = ["yosys", "-q", "-p", script]
    else:
        # Only the docker path needs an image: the caller's, else the one the
        # contract resolves (switch `image` > VIBEIC_LIBRELANE_IMAGE > this
        # host's released image). A refusal names the resolver's cause.
        if not image:
            import librelane_contract as _ll
            try:
                image = _ll.resolve_image(project)
            except _ll.Refusal as exc:
                raise Refusal("CDC_NETLIST_TOOL_UNAVAILABLE",
                              f"no yosys on PATH and no image: {exc}") from None
        import _docker_memory as _dmem
        mounts = {project} | {f.parent for f in files
                              if not f.parent.is_relative_to(project)}
        vols: List[str] = []
        for m in sorted(mounts):
            vols += ["-v", f"{m}:{m}"]
        argv = [docker, "run", *_dmem.docker_memory_flags(), "--rm", "--network", "none",
                "-u", f"{os.getuid()}:{os.getgid()}", *vols,
                "--entrypoint", "yosys", image, "-q", "-p", script]
    done = subprocess.run(argv, capture_output=True, text=True)
    log.write_text("$ " + " ".join(argv) + "\n" + done.stdout + done.stderr)
    if done.returncode or not raw_tmp.is_file():
        raise Refusal("CDC_NETLIST_BUILD_FAILED",
                      f"yosys rc={done.returncode}; {NETLIST_LOG_REL}")
    if source_binding(project, top, rtl_files) != binding:
        raise Refusal("CDC_NETLIST_STALE", "sources changed during native producer run")
    raw_tmp.replace(raw)
    import librelane_contract as ll
    raw_hash = ll.digest(raw)
    # Reuse the entire engine/container/memory/mount/user prefix. A fresh process
    # is necessary for this native normalization, not a different backend.
    normalize_argv = argv[:-3] + ["-q", "-p", normalization_script(raw, tmp)]
    normalized = subprocess.run(normalize_argv, capture_output=True, text=True)
    normalize_log.write_text("$ " + " ".join(normalize_argv) + "\n"
                             + normalized.stdout + normalized.stderr)
    if normalized.returncode or not tmp.is_file():
        raise Refusal("CDC_NETLIST_BUILD_FAILED",
                      f"normalization yosys rc={normalized.returncode}; "
                      f"{NETLIST_NORMALIZE_LOG_REL}")
    if (source_binding(project, top, rtl_files) != binding
            or ll.digest(raw) != raw_hash):
        raise Refusal("CDC_NETLIST_STALE", "sources or raw input changed during normalization")
    nl = load(tmp)
    if ((top and nl.top != top)
            or binding["options"]["declared_top"] not in (None, nl.top)):
        raise Refusal("CDC_NETLIST_TOP_MISMATCH", "native JSON top differs from requested/declared top")
    tmp.replace(out)
    ll.write_json(manifest, {
        "input": binding, "top": nl.top,
        "producer": {"step": "Yosys.JsonHeader", "argv": argv,
                     "exit_code": done.returncode, "image": image,
                     "source_root": str(project),
                     "normalization": {"argv": normalize_argv,
                                       "exit_code": normalized.returncode,
                                       "input_sha256": raw_hash},
                     "read_order": [os.path.relpath(f, project) for f in files]},
        "sha256": {"netlist.json": ll.digest(out), "netlist.yosys.log": ll.digest(log),
                   "netlist.raw.json": raw_hash,
                   "netlist.normalize.yosys.log": ll.digest(normalize_log)}})
    return out


# ─────────────────────────────── the model ────────────────────────────────

def _int(value) -> int:
    if isinstance(value, int):
        return value
    text = str(value)
    return int(text, 2) if set(text) <= {"0", "1"} else int(text)


@dataclass
class Flop:
    name: str
    type: str
    clk: object
    clk_pol: int
    d: List[object]
    q: List[object]
    arst: Optional[object] = None
    srst: Optional[object] = None      # outermost reset-mux select
    label: str = ""
    arst_pin: Optional[str] = None   # native pin; arst stays the shared reset bit
    arst_pol: Optional[int] = None   # active level at the native pin
    arst_value: Optional[List[str]] = None  # native Q/AD bit order (LSB first)
    arst_source: str = ""            # native cell source location
    srst_origin: str = "native_pin"  # an outer D-mux is only a role candidate


@dataclass
class Netlist:
    top: str
    ports: Dict[str, Tuple[str, List[object]]]
    cells: Dict[str, dict]
    names: Dict[object, str]
    drivers: Dict[object, Tuple[str, str]] = field(default_factory=dict)
    flops: List[Flop] = field(default_factory=list)
    memories: int = 0

    @property
    def port_bits(self) -> Dict[object, str]:
        return {b: n for n, (d, bits) in self.ports.items()
                if d in ("input", "inout") for b in bits}

    def is_const(self, bit) -> bool:
        return isinstance(bit, str)

    def flop_of_q(self) -> Dict[object, Flop]:
        return {b: f for f in self.flops for b in f.q}

    def root(self, bit, limit: int = 32) -> object:
        """Follow a net back through single-input buffers/inverters."""
        for _ in range(limit):
            drv = self.drivers.get(bit)
            if not drv:
                return bit
            cell = self.cells[drv[0]]
            if cell["type"] not in _TRANSPARENT:
                return bit
            bit = cell["connections"]["A"][0]
        return bit

    def bit_label(self, bit, port_labels: Optional[Dict[object, str]] = None) -> str:
        if self.is_const(bit):
            return f"const:{bit}"
        port = port_labels if port_labels is not None else {
            b: n for n, (_d, bits) in self.ports.items() for b in bits}
        if bit in port:
            return port[bit]
        return self.names.get(bit, f"net#{bit}")

    @property
    def clock_port_labels(self) -> Dict[object, str]:
        """Keep each vector port's native bit identity in clock domains.

        A bus name describes several independent clocks. Native bit numbers
        remain unambiguous across ascending/nonzero-based source ranges and
        aliases, without changing the ordinary signal/port census labels.
        """
        return {bit: (name if len(bits) == 1 else f"{name}:net#{bit}")
                for name, (_direction, bits) in self.ports.items()
                for bit in bits}

    def domain(self, flop: Flop,
               port_labels: Optional[Dict[object, str]] = None) -> str:
        return self.bit_label(self.root(flop.clk), self.clock_port_labels
                              if port_labels is None else port_labels)

    def sample_edge(self, flop: Flop) -> int:
        """Clock edge at the root net, accounting for transparent inversions."""
        bit = flop.clk
        edge = flop.clk_pol
        for _ in range(32):
            drv = self.drivers.get(bit)
            if not drv:
                break
            cell = self.cells[drv[0]]
            if cell["type"] not in _TRANSPARENT:
                break
            if cell["type"] in {"$not", "$_NOT_"}:
                edge ^= 1
            bit = cell["connections"]["A"][0]
        return edge

    def cone(self, bits: Iterable, skip: Optional[Set[object]] = None, *,
             q_of: Optional[Dict[object, Flop]] = None,
             ports: Optional[Dict[object, str]] = None
             ) -> Tuple[Set[object], Set[object]]:
        """Backward combinational cone. Returns (flop Q bits, port bits)."""
        q_of = self.flop_of_q() if q_of is None else q_of
        ports = self.port_bits if ports is None else ports
        seen: Set[object] = set()
        found_q: Set[object] = set()
        found_p: Set[object] = set()
        stack = [b for b in bits if not self.is_const(b)]
        while stack:
            bit = stack.pop()
            if bit in seen or (skip and bit in skip):
                continue
            seen.add(bit)
            if bit in q_of:
                found_q.add(bit)
                continue
            if bit in ports:
                found_p.add(bit)
                continue
            drv = self.drivers.get(bit)
            if not drv:
                continue
            cell = self.cells[drv[0]]
            if _is_flop_type(cell["type"]) or cell["type"] in _MEMORY:
                continue
            for pin, conn in cell["connections"].items():
                if cell.get("port_directions", {}).get(pin) == "output" or \
                        (not cell.get("port_directions") and pin in _OUTPUT_PORTS):
                    continue
                stack.extend(b for b in conn if not self.is_const(b))
        return found_q, found_p

    def direct_source(self, flop: Flop, index: int, *,
                      ports: Optional[Dict[object, str]] = None
                      ) -> Optional[object]:
        """The one bit D[index] samples with no logic between, else None.

        Passing a `$mux` is allowed when its other arm is a constant (reset or
        clear) or the flop's own Q (hold/enable): those arms add no data.
        """
        bit = flop.d[index]
        own = flop.q[index]
        ports = self.port_bits if ports is None else ports
        for _ in range(64):
            if self.is_const(bit):
                return None
            drv = self.drivers.get(bit)
            if not drv:
                return bit
            cell = self.cells[drv[0]]
            if _is_flop_type(cell["type"]) or bit in ports:
                return bit
            if cell["type"] in ("$buf", "$pos", "$_BUF_"):
                bit = cell["connections"]["A"][0]
                continue
            if cell["type"] in ("$mux", "$_MUX_"):
                conns = cell["connections"]
                pos = conns["Y"].index(bit)
                arms = (conns["A"][pos], conns["B"][pos])
                data = [a for a in arms if not self.is_const(a) and a != own]
                if len(data) != 1:
                    return None
                bit = data[0]
                continue
            return None
        return None


def _outer_reset_mux(nl: Netlist, d_bits: List[object]) -> Optional[object]:
    """The select of the $mux driving every D bit with a constant arm."""
    selects: Set[object] = set()
    for bit in d_bits:
        drv = nl.drivers.get(bit)
        if not drv:
            return None
        cell = nl.cells[drv[0]]
        if cell["type"] not in ("$mux", "$_MUX_"):
            return None
        conns = cell["connections"]
        pos = conns["Y"].index(bit)
        if not (nl.is_const(conns["A"][pos]) or nl.is_const(conns["B"][pos])):
            return None
        selects.add(conns["S"][0])
    return selects.pop() if len(selects) == 1 else None


def _aload_binary_value(nl: Netlist, bits: List[object],
                        ambiguous_drivers: Set[int]) -> Optional[List[str]]:
    """Prove literal AD or Slang's scalar logical-not of a binary literal.

    This is deliberately one native cell shape, with no traversal or general
    expression evaluation. Dynamic/unknown operands, cycles, other logic and
    multiply driven or externally driven nets cannot establish a reset value.
    The raw connectivity and reset pin remain untouched.
    """
    value = []
    for bit in bits:
        if bit in ("0", "1"):
            value.append(bit)
            continue
        driver = nl.drivers.get(bit)
        if (type(bit) is not int or not driver or bit in ambiguous_drivers
                or bit in nl.port_bits):
            return None
        cell = nl.cells[driver[0]]
        conn = cell.get("connections", {})
        if (cell["type"] != "$logic_not" or driver[1] != "Y"
                or set(conn) != {"A", "Y"} or conn["Y"] != [bit]
                or conn["A"] not in (["0"], ["1"])
                or cell.get("port_directions") != {"A": "input", "Y": "output"}):
            return None
        value.append("1" if conn["A"] == ["0"] else "0")
    return value


def load(path: Path, top: Optional[str] = None) -> Netlist:
    """Read a Yosys JSON netlist (JsonHeader shape) into the CDC model."""
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise Refusal("CDC_NETLIST_UNREADABLE", f"{path}: {exc}") from exc
    mods = doc.get("modules") if isinstance(doc, dict) else None
    if not isinstance(mods, dict) or not mods:
        raise Refusal("CDC_NETLIST_UNREADABLE", f"{path}: no modules")
    if top is None:
        tops = [n for n, m in mods.items()
                if _int(m.get("attributes", {}).get("top", 0) or 0)]
        if len(tops) != 1:
            tops = [n for n, m in mods.items()
                    if not _int(m.get("attributes", {}).get("blackbox", 0) or 0)]
        if len(tops) != 1:
            raise Refusal("CDC_NETLIST_TOP_AMBIGUOUS", f"{path}: {sorted(tops)}")
        top = tops[0]
    if top not in mods:
        raise Refusal("CDC_NETLIST_TOP_MISSING", f"{path}: {top}")
    mod = mods[top]
    ports = {n: (p.get("direction", ""), list(p.get("bits", [])))
             for n, p in mod.get("ports", {}).items()}
    names: Dict[object, str] = {}
    for n, net in sorted(mod.get("netnames", {}).items(),
                         key=lambda kv: (_int(kv[1].get("hide_name", 0)), kv[0])):
        for i, b in enumerate(net.get("bits", [])):
            if isinstance(b, int) and b not in names:
                width = len(net.get("bits", []))
                names[b] = n if width == 1 else f"{n}[{i}]"
    nl = Netlist(top=top, ports=ports, cells=mod.get("cells", {}), names=names)
    port_labels = {b: n for n, (_d, bits) in ports.items() for b in bits}
    ambiguous_drivers: Set[int] = set()
    for cname, cell in nl.cells.items():
        dirs = cell.get("port_directions") or {}
        for pin, conn in cell.get("connections", {}).items():
            out = dirs.get(pin) == "output" if dirs else pin in _OUTPUT_PORTS
            if out:
                for b in conn:
                    if isinstance(b, int):
                        if b in nl.drivers:
                            ambiguous_drivers.add(b)
                        nl.drivers[b] = (cname, pin)
        if cell["type"] in _MEMORY:
            nl.memories += 1
    for cname, cell in nl.cells.items():
        if not _is_flop_type(cell["type"]):
            continue
        c = cell["connections"]
        params = cell.get("parameters", {})
        internal = _INTERNAL_ADFF_RE.fullmatch(cell["type"])
        internal_dff = _INTERNAL_DFF_RE.fullmatch(cell["type"])
        if internal_dff:
            if (set(c) != {"C", "D", "Q"}
                    or len(c["C"]) != 1 or not c["D"] or len(c["D"]) != len(c["Q"])):
                raise Refusal("CDC_NETLIST_UNSUPPORTED_DFF",
                              f"{cname} ({cell['type']}): expected scalar C and matching D/Q")
            flop = Flop(name=cname, type=cell["type"], clk=c["C"][0],
                        clk_pol=1 if internal_dff.group(1) == "P" else 0,
                        d=list(c["D"]), q=list(c["Q"]))
            flop.srst = _outer_reset_mux(nl, flop.d)
            if flop.srst is not None:
                flop.srst_origin = "d_mux_candidate"
            flop.label = nl.bit_label(flop.q[0], port_labels).split("[")[0]
            nl.flops.append(flop)
            continue
        if internal:
            if (set(c) != {"C", "D", "Q", "R"}
                    or any(len(c[pin]) != 1 for pin in c)):
                raise Refusal("CDC_NETLIST_UNSUPPORTED_ASYNC_CONTROL",
                              f"{cname} ({cell['type']}): expected scalar C/D/Q/R")
            flop = Flop(name=cname, type=cell["type"], clk=c["C"][0],
                        clk_pol=1 if internal.group(1) == "P" else 0,
                        d=list(c["D"]), q=list(c["Q"]), arst=c["R"][0],
                        arst_pin="R", arst_pol=1 if internal.group(2) == "P" else 0,
                        arst_value=[internal.group(3)],
                        arst_source=cell.get("attributes", {}).get("src", ""))
            flop.label = nl.bit_label(flop.q[0], port_labels).split("[")[0]
            nl.flops.append(flop)
            continue
        async_pins = set(c) & {"ARST", "ALOAD", "SET", "CLR"}
        # One arst bit cannot represent independent set/clear controls. Refuse
        # at the shared loader so every ordinary CDC/RDC consumer fails closed.
        if cell["type"] in {"$dffsr", "$dffsre"} or async_pins & {"SET", "CLR"}:
            raise Refusal("CDC_NETLIST_UNSUPPORTED_ASYNC_CONTROL",
                          f"{cname} ({cell['type']}): multiple SET/CLR controls")
        arst_pin = "ARST" if "ARST" in c else None
        arst_pol = None
        arst_value = None
        if cell["type"] in {"$aldff", "$aldffe"}:
            # Slang preserves async loading even when AD is a constant reset
            # value. Only that single-control shape has the existing reset
            # semantics; dynamic AD must not disappear from data/reset analysis.
            try:
                arst_pol = _int(params["ALOAD_POLARITY"])
            except (KeyError, TypeError, ValueError):
                arst_pol = None
            arst_value = _aload_binary_value(nl, c.get("AD", []), ambiguous_drivers)
            if (async_pins != {"ALOAD"} or len(c["ALOAD"]) != 1
                    or c["ALOAD"][0] not in ("0", "1")
                    and not isinstance(c["ALOAD"][0], int)
                    or arst_pol not in (0, 1)
                    or len(c.get("CLK", [])) != 1
                    or not c.get("Q") or len(c.get("D", [])) != len(c["Q"])
                    or len(c.get("AD", [])) != len(c["Q"])
                    or arst_value is None):
                raise Refusal("CDC_NETLIST_UNSUPPORTED_ASYNC_CONTROL",
                              f"{cname} ({cell['type']}): expected one ALOAD, "
                              "binary polarity and constant binary AD matching Q")
            arst_pin = "ALOAD"
        elif "ALOAD" in c or "AD" in c:
            raise Refusal("CDC_NETLIST_UNSUPPORTED_ASYNC_CONTROL",
                          f"{cname} ({cell['type']}): unexpected ALOAD/AD pins")
        elif arst_pin:
            arst_pol = _int(params.get("ARST_POLARITY", 1))
            if "ARST_VALUE" in params:
                value = params["ARST_VALUE"]
                text = format(value, f"0{len(c.get('Q', []))}b") \
                    if isinstance(value, int) else str(value)
                arst_value = list(reversed(text))
        if "CLK" not in c:
            continue
        flop = Flop(name=cname, type=cell["type"], clk=c["CLK"][0],
                    clk_pol=_int(params.get("CLK_POLARITY", 1)),
                    d=list(c.get("D", [])), q=list(c.get("Q", [])),
                    arst=(c.get(arst_pin) or [None])[0],
                    arst_pin=arst_pin, arst_pol=arst_pol,
                    arst_value=arst_value,
                    arst_source=cell.get("attributes", {}).get("src", "")
                    if arst_pin else "")
        flop.srst = (c.get("SRST") or [None])[0]
        if flop.srst is None:
            flop.srst = _outer_reset_mux(nl, flop.d)
            if flop.srst is not None:
                flop.srst_origin = "d_mux_candidate"
        flop.label = nl.bit_label(flop.q[0], port_labels).split("[")[0] \
            if flop.q else cname
        nl.flops.append(flop)
    return nl


# ──────────────────────────────── the rules ───────────────────────────────

def _finding(rule: str, severity: str, message: str, **evidence) -> dict:
    return {"rule": rule, "severity": severity, "message": message,
            "file": NETLIST_REL, "line": 0, "evidence": evidence}


class _LookupSnapshot:
    """Indexes valid only for one analysis of the model's current state."""

    def __init__(self, nl: Netlist):
        self.nl = nl
        self.port_labels = {}
        clock_labels = {}
        for name, (_direction, bits) in nl.ports.items():
            for bit in bits:
                self.port_labels[bit] = name
                clock_labels[bit] = (name if len(bits) == 1 else
                                     f"{name}:net#{bit}")
        self.port_bits = {
            b: n for n, (direction, bits) in nl.ports.items()
            if direction in ("input", "inout") for b in bits}
        self.q_of = {b: f for f in nl.flops for b in f.q}
        self.domains = {
            id(f): nl.domain(f, clock_labels) for f in nl.flops}
        self.sample_edges = {id(f): nl.sample_edge(f) for f in nl.flops}
        self.labels = {
            id(f): (nl.bit_label(f.q[0], self.port_labels).split("[")[0]
                    if f.q else f.name)
            for f in nl.flops}
        self._direct_sources: Dict[Tuple[int, int], Optional[object]] = {}
        self._data_cones: Optional[List[Tuple[Flop, int, Set[object]]]] = None
        self._consumer_groups: Optional[
            Dict[int, List[Tuple[int, Flop, int, Optional[object]]]]] = None
        self._direct_consumers: Optional[
            Dict[object, List[Tuple[Flop, int]]]] = None
        self._cone_inputs: Dict[str, Tuple[object, ...]] = {}
        self._cone_reach: Dict[frozenset, Dict[str, int]] = {}
        self._terminals = list(self.q_of) + [b for b in self.port_bits if b not in self.q_of]
        self._q_count = len(self.q_of)
        self._terminal_masks = {bit: 1 << index
                                for index, bit in enumerate(self._terminals)}

    def domain(self, flop: Flop) -> str:
        return self.domains[id(flop)]

    def label(self, flop: Flop) -> str:
        return self.labels[id(flop)]

    def bit_label(self, bit) -> str:
        return self.nl.bit_label(bit, self.port_labels)

    def _cone_mask(self, bits: Iterable, skip: Optional[Set[object]] = None) -> int:
        """Share complete cell frontiers without expanding terminal sets per D bit.

        Keep the existing whole-cell conservative graph and iterative SCC
        closure. Only its frontier representation changes to integer masks;
        reset cuts remain separate and adjacency remains analysis-local.
        """
        cut = frozenset(skip or ())
        cache = self._cone_reach.setdefault(cut, {})

        def node(bit):
            if self.nl.is_const(bit) or bit in cut:
                return None, 0
            if bit in self._terminal_masks:
                return None, self._terminal_masks[bit]
            driver = self.nl.drivers.get(bit)
            if driver:
                name = driver[0]
                if self.nl.cells[name]["type"] not in FLOP_TYPES | _MEMORY:
                    return name, 0
            return None, 0

        mask, roots = 0, set()
        for bit in bits:
            name, terminal = node(bit)
            mask |= terminal
            if name is not None:
                roots.add(name)
        graph, frontiers = {}, {}
        pending = list(roots)
        while pending:
            name = pending.pop()
            if name in cache or name in graph:
                continue
            if name not in self._cone_inputs:
                cell = self.nl.cells[name]
                directions = cell.get("port_directions", {})
                self._cone_inputs[name] = tuple(dict.fromkeys(
                    bit for pin, conn in cell["connections"].items()
                    if not (directions.get(pin) == "output" or
                            (not directions and pin in _OUTPUT_PORTS))
                    for bit in conn if not self.nl.is_const(bit)))
            children, frontier = set(), 0
            for bit in self._cone_inputs[name]:
                child, terminal = node(bit)
                frontier |= terminal
                if child is not None:
                    children.add(child)
            graph[name] = children
            frontiers[name] = frontier
            pending.extend(children)

        # Iterative Kosaraju avoids recursion limits on deep native logic.
        # Edges point towards inputs; reversed component order resolves inputs
        # first. Already-cached descendants form complete frontier boundaries.
        seen, order = set(), []
        reverse = {name: [] for name in graph}
        for name, children in graph.items():
            for child in children:
                if child in graph:
                    reverse[child].append(name)
        for start in graph:
            stack = [(start, False)]
            while stack:
                name, done = stack.pop()
                if done:
                    order.append(name)
                elif name not in seen:
                    seen.add(name)
                    stack.append((name, True))
                    stack.extend((child, False) for child in graph[name]
                                 if child in graph and child not in seen)
        seen, components = set(), []
        for start in reversed(order):
            if start in seen:
                continue
            component, stack = [], [start]
            seen.add(start)
            while stack:
                name = stack.pop()
                component.append(name)
                for parent in reverse[name]:
                    if parent not in seen:
                        seen.add(parent)
                        stack.append(parent)
            components.append(component)
        for component in reversed(components):
            members = set(component)
            frontier = 0
            for name in component:
                frontier |= frontiers[name]
                for child in graph[name] - members:
                    frontier |= cache[child]
            for name in component:
                cache[name] = frontier
        for name in roots:
            mask |= cache[name]
        return mask

    def cone(self, bits: Iterable, skip: Optional[Set[object]] = None
             ) -> Tuple[Set[object], Set[object]]:
        """Preserve the public Q/port sets over the shared masked frontier."""
        mask = self._cone_mask(bits, skip)
        found_q, found_p = set(), set()
        while mask:
            lowest = mask & -mask
            index = lowest.bit_length() - 1
            (found_q if index < self._q_count else found_p).add(self._terminals[index])
            mask ^= lowest
        return found_q, found_p

    def direct_source(self, flop: Flop, index: int) -> Optional[object]:
        key = (id(flop), index)
        if key not in self._direct_sources:
            self._direct_sources[key] = self.nl.direct_source(
                flop, index, ports=self.port_bits)
        return self._direct_sources[key]

    def data_cones(self) -> List[Tuple[Flop, int, Set[object]]]:
        if self._data_cones is None:
            self._data_cones = []
            for flop in self.nl.flops:
                skip = {flop.srst} if flop.srst is not None else None
                for index, bit in enumerate(flop.d):
                    q_bits, port_bits = self.cone([bit], skip=skip)
                    self._data_cones.append(
                        (flop, index, q_bits | port_bits))
        return self._data_cones

    def consumers(self, source_bit, exclude_domain=None) -> List[Tuple[Flop, int, bool]]:
        # Store each destination once, grouped by its shared source mask.
        # Expanding the full source x destination relation eagerly can exhaust
        # memory even after cone traversal is fast. Ordinals retain the exact
        # former flop/D-bit order when groups are expanded on demand.
        if self._consumer_groups is None:
            self._consumer_groups = {}
            ordinal = 0
            for flop in self.nl.flops:
                skip = {flop.srst} if flop.srst is not None else None
                for index, bit in enumerate(flop.d):
                    mask = self._cone_mask([bit], skip)
                    self._consumer_groups.setdefault(mask, []).append(
                        (ordinal, flop, index, self.direct_source(flop, index)))
                    ordinal += 1
        source = self._terminal_masks.get(source_bit, 0)
        rows = [row for mask, group in self._consumer_groups.items()
                if mask & source for row in group
                if exclude_domain is None or self.domain(row[1]) != exclude_domain]
        rows.sort(key=lambda row: row[0])
        return [(flop, index, direct == source_bit)
                for _ordinal, flop, index, direct in rows]

    def sync_stage2(self, stage1: Flop, index: int, domain: str) -> bool:
        if self._direct_consumers is None:
            self._direct_consumers = {}
            for flop in self.nl.flops:
                for d_index in range(len(flop.d)):
                    source = self.direct_source(flop, d_index)
                    if source is not None:
                        self._direct_consumers.setdefault(source, []).append(
                            (flop, d_index))
        bit = stage1.q[index]
        return any(
            self.domain(flop) == domain
            # A two-flop synchroniser needs two samples on the same edge.
            # Compare at the root clock net: an inverted clock also changes
            # the sampling edge, even if both flop cells say positive edge.
            and self.sample_edges[id(flop)] == self.sample_edges[id(stage1)]
            and not (flop is stage1
                     and (d_index == index or flop.q[d_index] == bit))
            for flop, d_index in self._direct_consumers.get(bit, ()))


def _sync_stage2(nl: Netlist, stage1: Flop, index: int, domain: str,
                 lookup: Optional[_LookupSnapshot] = None) -> bool:
    """Is stage1.Q[index] sampled by a distinct bit lane of `domain`?"""
    return (lookup or _LookupSnapshot(nl)).sync_stage2(
        stage1, index, domain)


def _data_cones(nl: Netlist, lookup: Optional[_LookupSnapshot] = None
                ) -> List[Tuple[Flop, int, Set[object]]]:
    """Every flop D bit's cone, computed once per analysis.

    The sync-reset select is excluded: a reset reaching a flop is a reset
    question (the RDC rule), not a data crossing.
    """
    return (lookup or _LookupSnapshot(nl)).data_cones()


def _consumers(nl: Netlist, source_bit,
               lookup: Optional[_LookupSnapshot] = None, exclude_domain=None
               ) -> List[Tuple[Flop, int, bool]]:
    """(flop, D index, direct?) for every flop whose data cone reads the bit."""
    return (lookup or _LookupSnapshot(nl)).consumers(source_bit, exclude_domain)


def clock_domains(nl: Netlist, lookup: Optional[_LookupSnapshot] = None
                  ) -> List[str]:
    current = lookup or _LookupSnapshot(nl)
    return sorted({current.domain(f) for f in nl.flops})


def reg_crossing_findings(nl: Netlist,
                          lookup: Optional[_LookupSnapshot] = None) -> List[dict]:
    """A flop of domain A read by a flop of domain B (clock_domain_reg_crossing)."""
    import instrument_calibration
    instrument_calibration.assert_calibrated("_cdc_netlist::reg_crossing_findings")
    lookup = lookup or _LookupSnapshot(nl)
    domains = clock_domains(nl, lookup)
    if len(domains) < 2:
        return []
    findings: List[dict] = []
    per_pair: Dict[Tuple[str, str], List[Tuple[Flop, bool]]] = {}
    for src in nl.flops:
        send = lookup.domain(src)
        synced_all: Dict[str, bool] = {}
        for idx, bit in enumerate(src.q):
            for f, i, direct in _consumers(nl, bit, lookup, exclude_domain=send):
                recv = lookup.domain(f)
                if recv == send:
                    continue
                ok = direct and _sync_stage2(nl, f, i, recv, lookup)
                synced_all[recv] = synced_all.get(recv, True) and ok
        for recv, ok in synced_all.items():
            per_pair.setdefault((send, recv), []).append((src, ok))
    for (send, recv), rows in sorted(per_pair.items()):
        control = any(ok for _f, ok in rows)
        for src, ok in rows:
            width = len(src.q)
            label = lookup.label(src)
            ev = {"register": label, "width": width, "from_domain": send,
                  "to_domain": recv, "synchronised": ok,
                  "control_path_synchronised": control, "cell": src.name}
            if ok:
                if width > 1 and "gray" not in label.lower():
                    findings.append(_finding(
                        "CDC_MULTIBIT_NO_GRAY", "WARN",
                        f"{width}-bit '{label}' crosses '{send}'->'{recv}' "
                        f"through per-bit synchronisers with no gray evidence",
                        **ev, gray_evidence=False))
                continue
            qualified = control and width > 1
            findings.append(_finding(
                "CDC_UNSYNCED_DATA_QUALIFIED" if qualified else "CDC_REG_NO_SYNC",
                "WARN" if qualified else "ERROR",
                (f"{width}-bit '{label}' crosses '{send}'->'{recv}' "
                 f"unsynchronised beside a synchronised control path")
                if qualified else
                (f"'{label}' (clock '{send}') is read by clock '{recv}' "
                 f"with no 2-flop synchroniser"),
                **ev))
    return findings


def async_input_findings(nl: Netlist, is_candidate,
                         lookup: Optional[_LookupSnapshot] = None) -> List[dict]:
    """A top-level async input port sampled without a 2-flop synchroniser.

    `is_candidate(name)` is the regex gate's own port-name classifier; the
    candidate set is drawn from the netlist's PORTS only, so an internal net is
    never an async input whatever it is called (#2063).
    """
    import instrument_calibration
    instrument_calibration.assert_calibrated("_cdc_netlist::async_input_findings")
    lookup = lookup or _LookupSnapshot(nl)
    clock_or_reset = {nl.root(f.clk) for f in nl.flops} | \
        {nl.root(f.arst) for f in nl.flops if f.arst is not None}
    findings: List[dict] = []
    for name, (direction, bits) in sorted(nl.ports.items()):
        if direction not in ("input", "inout") or not is_candidate(name):
            continue
        for bit in bits:
            if bit in clock_or_reset:
                continue
            for f, i, direct in _consumers(nl, bit, lookup):
                if direct and _sync_stage2(
                        nl, f, i, lookup.domain(f), lookup):
                    continue
                label = lookup.label(f)
                findings.append(_finding(
                    "ASYNC_INPUT_NO_SYNC", "ERROR",
                    f"async input port '{name}' reaches flop '{label}' "
                    + ("through logic" if not direct else
                       "with no second synchroniser stage"),
                    port=name, flop=label, direct=direct))
                break
    return findings


def reset_role_candidates(nl: Netlist) -> List[dict]:
    """Intrinsic pre-adoption census; reviewed roles never erase requests."""
    return [{"state": f.name, "label": f.label, "q": f.q,
             "selector": f.srst,
             "source": nl.cells.get(f.name, {}).get("attributes", {}).get("src", "")}
            for f in sorted(nl.flops, key=lambda f: f.name)
            if f.srst is not None and not nl.is_const(f.srst)
            and f.srst_origin == "d_mux_candidate"]


def reset_dependency_findings(
        nl: Netlist, lookup: Optional[_LookupSnapshot] = None, *,
        metadata: Optional[dict] = None, reset_roles: Optional[dict] = None) -> List[dict]:
    """Complete reset-cycle detection; one ERROR witness per cyclic SCC.

    Reset roles and graph edges retain their existing meaning. Iterative
    Kosaraju visits the entire graph without a depth cap or simple-path
    enumeration. Sorting fixes traversal/witness order; the two SCC passes
    examine each node/edge exactly twice. Witness walks examine at most one
    further graph's worth of edges, with no recursion limit.
    """
    import instrument_calibration
    instrument_calibration.assert_calibrated("_cdc_netlist::reset_dependency_findings")
    lookup = lookup or _LookupSnapshot(nl)
    reset_roles = reset_roles or {}
    unresolved = [r for r in reset_role_candidates(nl)
                  if reset_roles.get(r["state"]) not in ("synchronous_reset", "functional_update")]
    resets: Dict[object, List[Flop]] = {}
    for f in nl.flops:
        srst = f.srst if (f.srst_origin == "native_pin"
                         or reset_roles.get(f.name) == "synchronous_reset") else None
        for r in (f.arst, srst):
            if r is not None and not nl.is_const(r):
                resets.setdefault(nl.root(r), []).append(f)
    reset_of: Dict[str, Set[object]] = {}
    for r, flops in resets.items():
        for f in flops:
            reset_of.setdefault(f.name, set()).add(r)
    edges: Dict[object, Set[object]] = {r: set() for r in resets}
    q_of = lookup.q_of
    for r in resets:
        qbits, _ports = lookup.cone([r])
        for qb in qbits:
            for r2 in reset_of.get(q_of[qb].name, ()):
                edges.setdefault(r2, set()).add(r)
    nodes = sorted(edges, key=str)
    graph = {node: tuple(sorted(edges[node], key=str)) for node in nodes}
    reverse: Dict[object, List[object]] = {node: [] for node in nodes}
    for node in nodes:
        for child in graph[node]:
            reverse[child].append(node)
    seen, order = set(), []
    node_visits = edge_visits = 0
    for start in nodes:
        if start in seen:
            continue
        seen.add(start)
        node_visits += 1
        stack = [(start, iter(graph[start]))]
        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
            except StopIteration:
                stack.pop()
                order.append(node)
                continue
            edge_visits += 1
            if child not in seen:
                seen.add(child)
                node_visits += 1
                stack.append((child, iter(graph[child])))
    seen, components = set(), []
    for start in reversed(order):
        if start in seen:
            continue
        component, pending = [], [start]
        seen.add(start)
        while pending:
            node = pending.pop()
            node_visits += 1
            component.append(node)
            for parent in reverse[node]:
                edge_visits += 1
                if parent not in seen:
                    seen.add(parent)
                    pending.append(parent)
        components.append(sorted(component, key=str))
    components.sort(key=lambda component: str(component[0]))

    findings: List[dict] = []
    witness_edge_visits = cyclic_nodes = 0
    for component in components:
        if len(component) == 1 and component[0] not in edges[component[0]]:
            continue
        cyclic_nodes += len(component)
        members = set(component)
        # Every vertex of a cyclic SCC has an internal successor. Following
        # the first sorted successor must repeat a vertex, yielding a real
        # closed cycle (not merely the SCC's ordered membership).
        positions, path = {}, []
        node = component[0]
        while node not in positions:
            positions[node] = len(path)
            path.append(node)
            for child in graph[node]:
                witness_edge_visits += 1
                if child in members:
                    node = child
                    break
        cycle = path[positions[node]:]
        first = min(range(len(cycle)), key=lambda i: str(cycle[i]))
        cycle = cycle[first:] + cycle[:first]
        labels = [lookup.bit_label(bit) for bit in cycle]
        findings.append(_finding(
            "CIRCULAR_RESET_DEPENDENCY", "ERROR",
            "reset net(s) " + " -> ".join(labels + [labels[0]])
            + " feed back through flops they reset",
            cycle=labels, cycle_bits=cycle))
    if metadata is not None:
        metadata.update({
            "reporting_policy": "one_witness_per_cyclic_scc",
            "cycle_detection_complete": not unresolved,
            "confirmed_reset_cycle_detection_complete": True,
            "all_cycles_enumerated": False,
            "reset_nodes": len(nodes),
            "reset_edges": sum(map(len, graph.values())),
            "scc_count": len(components),
            "cyclic_scc_count": len(findings),
            "acyclic_scc_count": len(components) - len(findings),
            "cyclic_scc_nodes": cyclic_nodes,
            "largest_scc_nodes": max(map(len, components), default=0),
            "witness_count": len(findings),
            "scc_nodes_visited": node_visits,
            "scc_edges_examined": edge_visits,
            "witness_edges_examined": witness_edge_visits,
            "intrinsic_role_candidates": len(reset_role_candidates(nl)),
            "unresolved_role_candidates": len(unresolved),
        })
    findings.extend(_finding(
        "RESET_ROLE_UNRESOLVED", "ERROR",
        f"state {row['label']!r} ({row['state']}) has a constant-arm D-mux "
        "whose reset/functional role is unresolved; current expert intent is required",
        candidate=row) for row in unresolved)
    return findings


def judge(nl: Netlist, rule: str, is_candidate=None, *,
          metadata: Optional[dict] = None, reset_roles: Optional[dict] = None) -> List[dict]:
    """The one entry every gate uses to judge a netlist.

    Each rule carries its own `assert_calibrated` line: one pair per rule, so
    a calibrated crossing rule cannot vouch for the reset rule.
    """
    lookup = _LookupSnapshot(nl)
    if rule == "reg_crossing":
        return reg_crossing_findings(nl, lookup)
    if rule == "async_input":
        return async_input_findings(
            nl, is_candidate or (lambda _n: False), lookup)
    if rule == "reset_dependency":
        return reset_dependency_findings(nl, lookup, metadata=metadata, reset_roles=reset_roles)
    raise ValueError(rule)


# ───────────────────────────── the dual arm ───────────────────────────────

def disagreement(regex_findings: List[dict], netlist_findings: List[dict],
                 regex_scanned: int) -> Dict[str, object]:
    """Name what one front end reports that the other does not.

    Findings are compared by (rule, blocking?) counts and by verdict; the
    two front ends name signals differently (source text vs netlist nets),
    so a per-signal comparison would report spelling, not disagreement.
    """
    def _block(rows):
        return sorted({r["rule"] for r in rows if r.get("severity") == "ERROR"})
    rv = "FAIL" if _block(regex_findings) else ("PASS" if regex_scanned else "NOT_MEASURED")
    nv = "FAIL" if _block(netlist_findings) else "PASS"
    return {"regex_verdict": rv, "netlist_verdict": nv,
            "regex_blocking_rules": _block(regex_findings),
            "netlist_blocking_rules": _block(netlist_findings),
            "agree": rv == nv and _block(regex_findings) == _block(netlist_findings)}


def netlist_for_gate(project: Path, explicit: Optional[str]) -> Optional[Path]:
    path = Path(explicit) if explicit else Path(project) / NETLIST_REL
    return path if path.is_file() else None


def resolve_mode(project: Path, front_end: Optional[str],
                 netlist_arg: Optional[str]) -> str:
    """`--front-end` wins; an explicit `--netlist` opts in; else the switch."""
    if front_end and front_end != "auto":
        return {"regex": "direct", "netlist": "librelane"}.get(front_end, front_end)
    if netlist_arg:
        return "librelane"
    return gate_mode(project)


def apply_front_end(project: Path, mode: str, netlist_arg: Optional[str],
                    rule: str, regex_findings: List[dict], regex_scanned: int,
                    is_candidate=None) -> Tuple[List[dict], Dict[str, object]]:
    """The findings a step-3 gate reports under `mode`, and what it read.

    direct    -> the regex findings, untouched.
    librelane -> the netlist findings only; no netlist is a blocking refusal.
    dual      -> the union, plus the named disagreement.
    """
    if mode == "direct":
        return regex_findings, {"front_end": "regex"}
    path = netlist_for_gate(project, netlist_arg)
    if path is None and not netlist_arg and not regex_scanned:
        # ORGANIC #887, HARVESTED onto the netlist front end (R-0929-TOOL-DEFAULT
        # amendment): a project with no RTL has nothing to elaborate, so there
        # is no netlist to expect. That is INPUT MISSING -- the gate examines
        # zero sources and discloses it (the shared vacuous rc) -- never a
        # plain PASS and never a netlist FAIL. RTL present without its netlist
        # still refuses below.
        return ([], {"front_end": "netlist" if mode == "librelane" else "dual",
                     "netlist": NETLIST_REL, "netlist_read": False,
                     "netlist_absent_reason": "no RTL source to elaborate"})
    if path is None:
        return ([_finding("NETLIST_MISSING", "ERROR",
                          f"step-3 mode '{mode}' needs the Yosys JSON netlist "
                          f"{netlist_arg or NETLIST_REL}; the regex front end is "
                          f"not substituted for it")],
                {"front_end": "netlist" if mode == "librelane" else "dual",
                 "netlist": str(netlist_arg or NETLIST_REL), "netlist_read": False})
    import instrument_calibration
    try:
        nl = load(path)
        binding = require_binding(project, path, nl)
        analysis: dict = {}
        roles = None
        if rule == "reset_dependency" and reset_role_candidates(nl):
            import ai_signed_judgement as expert
            roles, why = expert.reset_roles(project, nl, path)
            analysis["role_authority"] = why
            analysis["reset_role_request"] = expert.reset_role_request(project)
        rows = judge(nl, rule, is_candidate, metadata=analysis, reset_roles=roles)
    except (Refusal, instrument_calibration.Uncalibrated) as exc:
        code = getattr(exc, "code", "NETLIST_RULE_UNCALIBRATED")
        return ([_finding(code, "ERROR", str(exc))],
                {"front_end": mode, "netlist": str(path), "netlist_read": False})
    import hashlib
    extra: Dict[str, object] = {
        "netlist": str(path), "netlist_read": True,
        "netlist_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "netlist_top": nl.top, "netlist_flops": len(nl.flops),
        "netlist_clock_domains": clock_domains(nl),
        "netlist_input_fingerprint": binding["input"]["fingerprint"]}
    if rule == "reset_dependency":
        extra["reset_dependency_analysis"] = analysis
    if mode == "librelane":
        extra["front_end"] = "netlist"
        return rows, extra
    extra["front_end"] = "dual"
    extra["front_end_comparison"] = disagreement(regex_findings, rows, regex_scanned)
    return regex_findings + rows, extra
