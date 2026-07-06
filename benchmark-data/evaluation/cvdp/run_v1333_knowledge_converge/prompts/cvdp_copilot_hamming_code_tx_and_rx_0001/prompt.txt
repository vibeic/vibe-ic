Design a transmitter module **Module Name: hamming_code_tx_for_4bit** using SystemVerilog that encodes 4-bit input data (data_in) into an 8-bit output (data_out) using Hamming code principles for error detection. Hamming code helps generate parity bits, which are combined with the original data to detect and correct single-bit errors.

The relationship between number of data bits (m) and number of parity bits (p) follows the formula:
FORMULA: 2<sup>p</sup> ≥ (p + m) + 1

For 4 data bits, 3 parity bits are required, resulting in a total of 7 bits (3 parity + 4 data). An extra redundant bit is added to pad the output 8 bits. 

Additional Information: On the receiver side, if p is a 3-bit value, we have three syndrome bits (c3, c2, c1) calculated based on transmitted data and parity bits, to identify the position of the error bit within a total of 7 bits (3 parity bits + 4 data bits). Adding an extra redundant bit as the least significant bit in the transmitter keeps the actual 7 bits used in Hamming error detection separate (`data_out[7:1]`), simplifying the error location process where the 3 syndrome bits (c3, c2, c1) directly map to these 7 bits.

The parity bits are calculated using XOR operations to ensure "even parity," which guarantees that the number of 1s in specified bit groups is even. They are placed at specific positions to ensure each bit position in the data can be checked for single-bit errors. These parity bit positions correspond to powers of 2 in the output structure (positions 1, 2, and 4 in this 8-bit layout), allowing for targeted error detection.

Design the module that generates these parity bits and outputs the final 8-bit encoded signal for transmission.

### 1 Input/Output Specifications:

1. Input:
     `data_in[3:0]`: A 4-bit input signal representing the original data to be transmitted.
3. Output:
     `data_out[7:0]`: An 8-bit output signal representing the encoded data.

### 2 Behavioral Definition:

The module should encode the data based on the following steps:

1. `data_out[0]`: This bit is fixed to 0 as a redundant bit.
2. `data_out[1]`: This is a parity bit, calculated using the XOR operation to ensure even parity of the input bits (`data_in`) at positions 0, 1, and 3 of data_in.
3. `data_out[2]`: Another parity bit, calculated using XOR for even parity, but this time based on input bits (`data_in`) at positions 0, 2, and 3 of data_in.
4. `data_out[4]`: A third parity bit, also using XOR for even parity, calculated based on input bits (`data_in`) at positions 1, 2, and 3 of data_in.
5. `data_out[3]`, `data_out[5]`, `data_out[6]`, `data_out[7]`: These are assigned `data_in[0]`, `data_in[1]`, `data_in[2]`, `data_in[3]` respectively, preserving the order of the input data.

### 3 Timing and Synchronization:
This design is purely combinational. The output must be immediately updated with a change in the input.

### 4 Edge Cases:
Assume that data_in will always be a valid 4-bit signal of 1s and 0s (including all zero input). Therefore, there is no need to handle invalid input cases explicitly.