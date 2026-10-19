# Hardware Interfaces
The module **`packet_engine`** has the following hardware interfaces defined.

## Inter-Module Signals
| Port Name | Package::Struct | Type | Act | Width | Description |
|:--|:--|:--|:--|--:|:--|
| link | neutral_pkg::link | req_rsp | req | 1 | One requester interface |
| transport | neutral_pkg::transport | req_rsp | rsp | 1 | One responder interface |
| status | neutral_pkg::flag4 | uni | req | 1 | An internal encoded status |

## Other Signals
| Signal | Direction | Type | Description |
|:--|:--|:--|:--|
| clk_i | input | logic | Primary clock input |
| rst_ni | input | logic | Active-low reset input |
| token_i | input | misspelled_pkg::token_t | Nominal input with an explicit source spelling error |
| code_i | input | neutral_pkg::code_t | Nominal code input |
| status_o | output | logic | Scalar external status output |

The engineering choice corrects the token package spelling to neutral_pkg and
keeps the scalar external status separate from the internal encoded status.
The requester expands to link_req_o and link_rsp_i. The responder expands to
transport_req_i and transport_rsp_o. These names are selected engineering configuration.
