# Changelog

All notable changes to the `vibe-ic` plugin are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Initial public release

First public release. Claude Code plugin driving an AI-native IC design
flow from natural-language intent through tape-out sign-off.

### Added

- **Skills** (~85): Phase 1 doc extraction (17), Phase 2a (RTL +
  verification), Phase 2b (FPGA prototype), Phase 3 (synthesis →
  STA → DFT → PnR → DRC/LVS → tape-out), analog A1-A9, mixed-signal
  M1-M4.
- **Deterministic programs** (~220): canonical-flow compliance checks,
  structural-RTL gates, anti-fabrication audit suite, IP catalog
  reproducible pull.
- **Chip-AGNOSTIC source guard**: `tests/chip_deny_list.txt` +
  `tests/test_chip_agnostic_guard.py` enforce that no private IC or
  vendor name leaks into source.
- **Single entry point**: `/vibe-ic-phase1`, `/vibe-ic-phase2`,
  `/vibe-ic-phase3` slash commands.
