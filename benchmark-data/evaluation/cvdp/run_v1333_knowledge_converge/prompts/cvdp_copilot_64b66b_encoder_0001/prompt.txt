Design a 64b/66b encoder that supports data encoding with a 2-bit sync header. The encoder should take a 64-bit data input and a corresponding 8-bit control word. The 8-bit control word indicates which data octets (8-bit segments) within the 64-bit word are either pure data or contain control characters. Implement only pure data encoding that encodes 64b to 66b when the 8-bit control word is 8'b00000000.

### Design Specification:

A 64b/66b encoder is a digital circuit that converts a 64-bit data word into a 66-bit encoded output, commonly used in high-speed communication protocol like Ethernet. This encoding scheme appends a 2-bit sync header to the data to maintain synchronization and differentiate data from control words using 8-bit control input.

#### Control Word Interpretation:
The encoder receives both:
- A **64-bit data word**: Represented as 8 octets (8-bit segments).
- An **8-bit control word**: Each bit represents whether the corresponding data octet contains pure data (`0`) or a control character (`1`).
- **Control Bit = 0**: Indicates a pure data octet.
- **Control Bit = 1**: Indicates a control character in the corresponding data octet, but only pure data encoding has to be implemented in the RTL.

#### Supported Sync Word and Output Behavior:
The encoder appends a 2-bit sync header at the MSBs of the encoded output, based on the presence of control characters:
- **Sync Word and Output data**:
  - `2'b01`: All 8 octets are pure data. The 64-bit data word is passed directly to the encoded output.
  - `2'b10`: At least one of the 8 octets is a control character. However, 64'd0 is passed in the output as control word encoding is not supported.

### Inputs and Outputs:

- **Inputs**:
  - `clk_in`:  clock signal, triggering on the rising edge.
  - `rst_in`: 1-bit Active HIGH asynchronous reset. When HIGH, the `encoder_data_out` is zero
  - `encoder_data_in ([63:0])`: 64-bit data word.
  - `encoder_control_in ([7:0])`: 8-bit control word indicating pure data (`0`) or control character (`1`) per octet. A value of `8'b00000000` indicates data encoding.

- **Output**:
  - `encoder_data_out ([65:0])`: 66-bit encoded output, consisting of a 2-bit sync word at the MSBs followed by 64-bit data word. Output Latency is one clock cycle.

### Example Operations:

**Example 1**: Encoding a Data Word (All Data Octets)

- **Input**: `encoder_control_in = 8'b00000000`, `encoder_data_in = 64'hA5A5A5A5A5A5A5A5`
- **Expected Output**: `encoder_data_out = {2'b01, 64'hA5A5A5A5A5A5A5A5}`

**Example 2**: Control Word (Not Supported in RTL)

- **Input**: `encoder_control_in = 8'b00001111`, `encoder_data_in = 64'hA5A5A5A5A5A5A5A5`
- **Expected Output**: `encoder_data_out = {2'b10, 64'h0000000000000000}`