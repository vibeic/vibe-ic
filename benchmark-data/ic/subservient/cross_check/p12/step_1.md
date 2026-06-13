# Step 1 — Spec-to-RTL — REUSED-IP core + GENERATED glue

Verdict: DIFFERENT-BUT-OK

spec-to-RTL WAIVED (a full RISC-V SoC is not datasheet-generatable). OUR run pulled the GENUINE SERV core (REUSED-IP, github.com/olofk/serv@1.4.0) and GENERATED only the chip-top + GPIO + WB->8b-SRAM bridge. The golden also used catalog-glue but STUBBED its core. Same REUSED-IP family; the GENERATED glue differs by design. DIFFERENT-BUT-OK (and OURS drives a genuine core, golden stubbed — see §3).
