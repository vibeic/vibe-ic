riscv_isa_ref_oracle — a PROVEN reference kit for the differential oracle that
`cpu_isa_ref_oracle_capability_probe.py` reports as CONSTRUCTIBLE.

WHY THIS EXISTS
---------------
`cap:cpu_functional_oracle` used to be waived as a capability gap: "a per-IC
functional oracle cannot be constructed for a memory-bus CPU top". The probe
measures that claim and, for the RISC-V family, finds it false — the flow's own
container ships `spike` (the reference ISA simulator) and a RISC-V cross
toolchain. The gap is a GENERATOR gap. This directory is the worked reference
that a generator has to reproduce, so the FAIL the probe arms is actionable
instead of merely correct.

THE SHAPE OF THE ORACLE
-----------------------
No per-IC golden vectors are authored. Instead:

  1. Compile firmware ONCE from a chip-agnostic source.
  2. Execute it on the REFERENCE MODEL  -> golden.
  3. Execute the SAME image on the DUT  -> observed.
  4. Compare the architectural result at the chip boundary.

THE ONE NON-OBVIOUS CONSTRAINT
------------------------------
spike owns [0, 0x1000) for its debug module, so its DRAM cannot be based at 0,
while a CPU whose RESET_PC is 0 must be linked at 0. The kit therefore links the
SAME source twice (`link.ld` at 0, `link_spike.ld` at 0x80000000) and makes the
comparison sound by construction:

  * every PC-dependent contribution to the signature is folded as a PC-RELATIVE
    difference (`auipc`/`auipc`/`sub`, `auipc`/`jal`/`sub`), and
  * addresses are materialised with explicit `lui %hi` / `addi %lo` under
    `-mno-relax`, so both links assemble to the same instruction count,

then PROVES it: the two `.text` images must differ in ZERO non-LUI words. On the
worked example (`subservient` / SERV, rv32i_zifencei) that check reports
`text bytes: 808 808 / differing words: 2 / NON-LUI differences: 0`.

WHAT THE TB OBSERVES
--------------------
`tb_case.v.in` reads its expectations at RUNTIME from spike-derived files; it
contains no hand-written expected value and `$fatal`s on any mismatch.

  * the final SRAM image, word for word — written ONLY through the chip's own
    memory port group, so this half is fully black-box
  * every peripheral write transaction, captured on the bus STROBE RISING EDGE
    (a protocol event) rather than on the peripheral's own latch condition
  * what the peripheral PIN settled to after each transaction

That last two-way split matters: an earlier version of this monitor reused the
GPIO block's own latch condition, and a mutation of that condition then hid
inside the observer. The mutation control caught it. Do not re-couple them.

THE BINDING THE GENERATOR STILL HAS TO SOLVE
--------------------------------------------
`tb_case.v.in` is written against ONE memory-bus profile — a generic 32-bit word
port with byte write-selects and a synchronous registered read
(`o_*_adr / o_*_wdata / o_*_wsel / o_*_we / o_*_cyc / i_*_rdata`). A generator
must READ the profile from the design's declaration (e.g. declaration.json's
`sram_interface_protocol`) and REFUSE — with a report naming what it found, the
profiles it can bind, and the field that would let it bind — when the profile is
unknown. Guessing a bus binding would put the oracle's credibility back where
`cap:cpu_functional_oracle` left it. Extension points that matter next:
wishbone_classic, ahb_lite, axi4_lite.

MANDATORY: THE ORACLE MUST BE MUTATION-CONTROLLED
-------------------------------------------------
An oracle nobody has seen fail is not evidence. On the worked example five
killable mutants (adder carry-in dropped; compare carry inverted; peripheral
data inverted; memory byte-select lane stuck; memory word-address bit flipped)
were ALL killed, and one timing-equivalent mutant (peripheral latch phase moved
inside a 2-cycle write, where the settled pin value provably cannot change)
survived and is recorded as equivalent rather than counted as a pass.

FILES
-----
  common.inc                     shared prologue/epilogue macros
  isa_rv32i_exercise.S           ~90 base-integer instructions folded into a
                                 32-bit signature
  isa_zifencei_selfmodify.S      store-over-instruction + FENCE.I + execute
  io_toggle.S                    regular peripheral toggling
  io_byte_stream.S               serialises a byte string over a 1-bit port
  link.ld / link_spike.ld        the two links
  tb_case.v.in                   TB template (@CASE@, @NGPIO@)
  gen_cases.py                   build -> prove-same-program -> spike -> golden
                                 -> emit TB -> run -> compare
