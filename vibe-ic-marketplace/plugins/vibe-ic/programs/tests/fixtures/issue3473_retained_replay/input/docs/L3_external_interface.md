# External interface

| Port | Width | Direction | Meaning |
| --- | --- | --- | --- |
| `clk` | 1-bit | input | Rising-edge clock. |
| `rst` | 1-bit | input | Synchronous active-high reset. |
| `x` | N-bit (`[size-1:0]`, parameter `size` default 32) | input | Unsigned parallel multiplicand. |
| `y` | 1-bit | input | Unsigned serial multiplier bit. |
| `p` | 1-bit | output | Serial product bit. |

## Design parameters

| Parameter | Default | Type |
| --- | --- | --- |
| `size` | 32 | Any positive integer of at least 4; 8, 16, and 32 are representative configurations. |

All inputs are sampled on the rising edge of `clk`. There is no ready/valid
handshake and no bidirectional or tri-state port.
