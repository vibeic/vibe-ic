# PRACTICAL_NOTES — spi-peripheral (community contribution)

## Common gotchas

- **Mode-0 vs mode-3 mismatch** is the #1 cause of SPI bring-up failure on
  first power-on. Sample with both modes during loopback test before
  declaring the bus broken.
- **CSn deassertion timing**: many slaves require CSn to stay low for the
  ENTIRE transaction. Glitches between bytes (e.g. from FIFO underrun on
  master side) cause silent data corruption.
- **MISO float during read**: when CSn is high, slave's MISO must
  tristate. Failing to do so blocks every other slave on the same bus.

## Verification recommendations

- Lint-check that every always_ff block driving MISO has a `CSn ? 1'bz : ...`
  pattern.
- Cocotb stimulus must include back-to-back transactions with minimum
  inter-transaction gap (1 SCK period) to catch FSM-reset bugs.
