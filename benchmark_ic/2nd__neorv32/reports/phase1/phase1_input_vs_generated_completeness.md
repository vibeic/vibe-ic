# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: FAIL
**Raw cell matches across non-reference docs**: 2705
  - design cells (clean context, gated): 2703
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 2
**Captured (program + AI)**: 1886 (69.8%)
**Program-only cells**: 1878
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 817

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| references__riscv-privileged.txt | 575 | 575 | 0 | 382 | 0 | 193 | FAIL |
| Doxyfile.txt | 356 | 356 | 0 | 25 | 0 | 331 | FAIL |
| references__riscv-unprivileged.txt | 335 | 334 | 1 | 329 | 0 | 5 | FAIL |
| datasheet__cpu_csr.txt | 302 | 302 | 0 | 226 | 0 | 76 | FAIL |
| references__riscv-debug-specification.txt | 222 | 221 | 1 | 193 | 0 | 28 | FAIL |
| datasheet__soc.txt | 155 | 155 | 0 | 152 | 0 | 3 | FAIL |
| datasheet__soc_sysinfo.txt | 115 | 115 | 0 | 68 | 0 | 47 | FAIL |
| datasheet__cpu.txt | 110 | 110 | 0 | 65 | 0 | 45 | FAIL |
| datasheet__software_bootloader.txt | 97 | 97 | 0 | 85 | 0 | 12 | FAIL |
| datasheet__on_chip_debugger.txt | 95 | 95 | 0 | 84 | 0 | 11 | FAIL |
| references__riscv-asm.txt | 75 | 75 | 0 | 61 | 0 | 14 | FAIL |
| datasheet__soc_tracer.txt | 68 | 68 | 0 | 63 | 0 | 5 | FAIL |
| legal.txt | 67 | 67 | 0 | 67 | 0 | 0 | PASS |
| datasheet__soc_uart.txt | 61 | 61 | 0 | 59 | 0 | 2 | FAIL |
| datasheet__soc_neoled.txt | 60 | 60 | 0 | 57 | 0 | 3 | FAIL |
| datasheet__software.txt | 59 | 59 | 0 | 58 | 0 | 1 | FAIL |
| datasheet__soc_twd.txt | 56 | 56 | 0 | 56 | 0 | 0 | PASS |
| userguide__litex_support.txt | 56 | 56 | 0 | 56 | 0 | 0 | PASS |
| datasheet__soc_onewire.txt | 53 | 53 | 0 | 44 | 0 | 9 | FAIL |
| userguide__simulating_the_processor.txt | 53 | 53 | 0 | 53 | 0 | 0 | PASS |
| datasheet__soc_twi.txt | 50 | 50 | 0 | 50 | 0 | 0 | PASS |
| datasheet__overview.txt | 47 | 47 | 0 | 46 | 0 | 1 | FAIL |
| datasheet__cpu_isa.txt | 45 | 45 | 0 | 45 | 0 | 0 | PASS |
| references__riscv-c-api.txt | 40 | 40 | 0 | 40 | 0 | 0 | PASS |
| datasheet__soc_slink.txt | 39 | 39 | 0 | 38 | 0 | 1 | FAIL |
| userguide__using_ocd.txt | 39 | 39 | 0 | 33 | 0 | 6 | FAIL |
| datasheet__soc_trng.txt | 36 | 36 | 0 | 35 | 0 | 1 | FAIL |
| datasheet__soc_sdi.txt | 35 | 35 | 0 | 35 | 0 | 0 | PASS |
| datasheet__soc_spi.txt | 34 | 34 | 0 | 34 | 0 | 0 | PASS |
| datasheet__software_rte.txt | 34 | 34 | 0 | 23 | 0 | 11 | FAIL |
| datasheet__soc_gpio.txt | 30 | 30 | 0 | 25 | 0 | 5 | FAIL |
| references__riscv-aclint-1.0-rc4.txt | 29 | 29 | 0 | 27 | 0 | 2 | FAIL |
| datasheet__soc_dma.txt | 28 | 28 | 0 | 27 | 0 | 1 | FAIL |
| datasheet__soc_cfs.txt | 26 | 26 | 0 | 25 | 0 | 1 | FAIL |
| datasheet__soc_gptmr.txt | 26 | 26 | 0 | 26 | 0 | 0 | PASS |
| datasheet__soc_pwm.txt | 25 | 25 | 0 | 25 | 0 | 0 | PASS |
| datasheet__soc_clint.txt | 23 | 23 | 0 | 23 | 0 | 0 | PASS |
| datasheet__soc_wdt.txt | 23 | 23 | 0 | 21 | 0 | 2 | FAIL |
| references__riscv-semihosting.txt | 22 | 22 | 0 | 19 | 0 | 3 | FAIL |
| userguide__adding_custom_hw_modules.txt | 22 | 22 | 0 | 22 | 0 | 0 | PASS |
| userguide__packaging_vivado.txt | 22 | 22 | 0 | 21 | 0 | 1 | FAIL |
| datasheet__cpu_cfu.txt | 20 | 20 | 0 | 15 | 0 | 5 | FAIL |
| userguide__general_hw_setup.txt | 18 | 18 | 0 | 18 | 0 | 0 | PASS |
| datasheet__soc_imem.txt | 16 | 16 | 0 | 16 | 0 | 0 | PASS |
| userguide__eclipse_ide.txt | 16 | 16 | 0 | 16 | 0 | 0 | PASS |
| references__riscv-calling.txt | 15 | 15 | 0 | 15 | 0 | 0 | PASS |
| datasheet__soc_dmem.txt | 13 | 13 | 0 | 13 | 0 | 0 | PASS |
| datasheet__soc_xbus.txt | 13 | 13 | 0 | 13 | 0 | 0 | PASS |
| datasheet__cpu_dual_core.txt | 12 | 12 | 0 | 12 | 0 | 0 | PASS |
| datasheet__soc_dcache.txt | 11 | 11 | 0 | 9 | 0 | 2 | FAIL |
| userguide__micropython_port.txt | 11 | 11 | 0 | 8 | 0 | 3 | FAIL |
| userguide__sw_toolchain_setup.txt | 11 | 11 | 0 | 11 | 0 | 0 | PASS |
| Makefile.txt | 9 | 9 | 0 | 9 | 0 | 0 | SKIP_LOW_TOKENS |
| datasheet__soc_icache.txt | 9 | 9 | 0 | 9 | 0 | 0 | SKIP_LOW_TOKENS |
| userguide__neorv32_in_verilog.txt | 9 | 9 | 0 | 9 | 0 | 0 | SKIP_LOW_TOKENS |
| datasheet__soc_bootrom.txt | 7 | 7 | 0 | 7 | 0 | 0 | SKIP_LOW_TOKENS |
| datasheet__index.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| references__riscv-zibi.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| userguide__index.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| userguide__installing_an_executable.txt | 5 | 5 | 0 | 5 | 0 | 0 | SKIP_LOW_TOKENS |
| userguide__rust_support.txt | 5 | 5 | 0 | 5 | 0 | 0 | SKIP_LOW_TOKENS |
| attrs.txt | 4 | 4 | 0 | 4 | 0 | 0 | SKIP_LOW_TOKENS |
| userguide__zephyr_support.txt | 4 | 4 | 0 | 4 | 0 | 0 | SKIP_LOW_TOKENS |
| README.txt | 3 | 3 | 0 | 3 | 0 | 0 | SKIP_LOW_TOKENS |
| datasheet__main.txt | 3 | 3 | 0 | 3 | 0 | 0 | SKIP_LOW_TOKENS |
| userguide__application_program_compilation.txt | 3 | 3 | 0 | 3 | 0 | 0 | SKIP_LOW_TOKENS |
| userguide__building_the_documentation.txt | 3 | 3 | 0 | 3 | 0 | 0 | SKIP_LOW_TOKENS |
| userguide__main.txt | 3 | 3 | 0 | 3 | 0 | 0 | SKIP_LOW_TOKENS |
| figures__README.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| doxygen_main.txt | 1 | 1 | 0 | 1 | 0 | 0 | SKIP_LOW_TOKENS |
| userguide__free_rtos_support.txt | 1 | 1 | 0 | 1 | 0 | 0 | SKIP_LOW_TOKENS |
| datasheet__content.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |
| figures__.gitignore.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |
| userguide__content.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 10 | 0 |  |
| L11_OTP_CONTENT | 1 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 4 | 0 |  |
| L13_LAB_CALIBRATION | 1 | 0 |  |
| L1_DATASHEET | 1460 | 0 |  |
| L2_FRS | 531 | 0 |  |
| L3_CMD_PROTOCOL | 5 | 0 |  |
| L4_REGMAP | 448 | 0 |  |
| L5_ADI_SPEC | 251 | 0 |  |
| L6_CONTROL_LOGIC | 13 | 0 |  |
| L7_TEST_DEBUG | 10 | 0 |  |
| L8_RTL_CONSTANTS | 260 | 0 |  |
| L8_TIMING_WAVEFORM | 26 | 0 |  |
| L9_INTEGRATION_SPEC | 243 | 0 |  |
| (unallocated) | 0 | 0 | 817 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
