A **AXI stream data upsizer** is a digital circuit used to upscale single-channel input data from a smaller 24-bit width to a larger width of 32-bits, supporting features like sign extension, and data format selection, while maintaining a single pipeline register stage.

## Design Specification of `axis_upscale` module:

### Interface:

#### Inputs:
- **`clk`** (1-bit): Global Clock signal.
- **`resetn`** (1-bit): An active-low synchronous reset signal. When asserted, this signal resets the internal flip-flops, forcing the output to a known state.

- **`dfmt_enable`** (1-bit): Data format enable.
- **`dfmt_type`** (1-bit): Data format type 1 = inverted version of slave MSB will be carry forwarded, 0 = slave msb slave msb will be carry forwarded.
- **`dfmt_se`** (1-bit): Data format sign extension, 1= expected 23rd bit will be extended, 0 = 0 will be extended.

- **`s_axis_valid`** (1-bit): Indicates that the slave is driving a valid transfer.
- **`s_axis_data`** (24-bits, [23:0] ): This is the primary payload data from AXI slave.
- **`m_axis_ready`** (1-bit):  indicates that the slave can accept a transfer in the current cycle.

#### Output:
- **`s_axis_ready`** (1-bit): Indicates that the slave can accept a transfer in the current cycle.
- **`m_axis_valid`** (1-bit): Indicates that the master is driving a valid transfer.
- **`m_axis_data`** (32-bits, [31:0] ): This is the primary payload data to AXI master.

### Description of AXI stream data upsizer Functionality:

 The functionality `axis_upscale` module is to upscale single-channel input data from a smaller width to a larger width. and when upscaling the extra bit positions will be filed with zero's or one's based on the data format signals such as `dfmt_type`, `dfmt_se` and `dfmt_enable`. each signals functionality is explained below

- `dfmt_enable`: Data format enable. if this enabled then only the other 2 signal are valid, if `dfmt_enable` is disabled output data will be concatenation of 24 times zero and input `s_axis_data` data.

- `dfmt_type`: Data format type if `dfmt_type` = 1, then inverted version of `s_axis_data's` MSB will be carry forwarded, and for 0  `s_axis_data's` MSB will be carry forwarded to m_axis_data[23].

- `dfmt_se` Data format sign extension, if `dfmt_se` 1= expected 23rd bit of `s_axis_data's` will be extended, if `dfmt_se` = 0, zero will be extended.

**Reset Behavior (resetn):**
- When the` resetn` signal is de-asserted (active low):
- All flip-flops in the encoder are reset to a known state (typically logic low).
- The `m_axis_data` signal is held at a known value (e.g., all zeroes) while the reset is active.

