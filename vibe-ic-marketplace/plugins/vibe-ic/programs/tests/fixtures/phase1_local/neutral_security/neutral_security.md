# NeutralCore

## Security Requirements

## Key handling
The session key shall be cleared when reset is asserted.

## Side-channel countermeasures
The datapath shall use first-order masking against differential power analysis.

## Fault injection countermeasures
On detecting a fatal fault the unit shall stop releasing output until reset.
