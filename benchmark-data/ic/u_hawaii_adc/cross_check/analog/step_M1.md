# Step M1 — A+D top integration (hardmacro instantiation)  ·  Verdict: IN-RANGE
OURS: analog hardmacros (LEF/Lib/.v) for ldo + delta_sigma are ready to instantiate in a chip top (6x delta_sigma array + 1 LDO), matching the UHEE628 top-pin contract (IN1-6/OUT1-6/CK4-6/IOVDD/CORE/VLDO/VREF).
REF: golden chip top = exactly this array (6 modulators + LDO), 1480x1480 um. Integration intent matches.
NOTE: this IC has NO synthesizable digital RTL (the 1-bit serial decimator is out of L5 scope; output is a raw bitstream) -> the A+D integration is analog-hardmacro-level, not RTL-synth-level.
