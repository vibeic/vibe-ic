Design a SystemVerilog module named `hamming_code_receiver` that decodes an 8-bit input signal and detects single-bit errors using Hamming code principles. The receiver performs "even parity checks" to identify any single-bit errors in `data_in` and provides corrected 4-bit data to output port `data_out[3:0]` 

### 1. Inputs
- **`data_in[7:0]`**:  8-bit input signal containing 4 data bits, 3 parity bits, and 1 redundant bit

### 2. Outputs
- **`data_out[3:0]`**: An 4-bit output signal containing the corrected data if an error is detected. If no error is detected, this output will mirror the data bits in the the input (`data_in`).

### 3. Explanation of Data Structure

The transmitted data includes 4 data bits and 3 parity bits, organized within `data_in[7:1]`. An extra redundant bit at `data_in[0]` extends the input to 8 bits, separating the 7 bits used in Hamming code error detection (`data_in[7:1]`) from the redundant bit. This organization allows the receiver to calculate three syndrome bits {`c1, c2, c3`}, which directly indicate the position of any error among the 7 significant bits in `data_in[7:1]`.

### 4. Behavioral Definition 
The receiver’s task is to decode this 7-bit data (`data_in[7:1]`), and detect errors using the even parity error detection (by performing XOR on specific data and parity bits of `data_in` as explained below).

- **Parity bits** are placed at positions that are **powers of 2** in `data_in`:
  - 2<sup>0</sup> = 1, 2<sup>1</sup> = 2, 2<sup>2</sup> = 4
- **Data bits** are placed **sequentially** at positions that are **Non powers of 2** in `data_in`,  as given below.

| Position  | Index | Type      
|-----------|-------|-----------|
| 000       | 0     | Redundant |
| 001       | 1     | Parity bit 1  |
| 010       | 2     | Parity bit 2  |
| 011       | 3     | Data bit 1    |
| 100       | 4     | Parity bit 3  |
| 101       | 5     | Data bit 2   |
| 110       | 6     | Data bit 3   |
| 111       | 7     | Data bit 4   |

4.1 **Even Parity Error Detection Logic:**

Since there are 3 parity bits, the **even parity error detector logic** produces 3-bits `{c1, c2, c3}`. 

#### c3:
- Check all positions in `data_in` where the binary index has a 1 in the least significant bit (LSB) position (00**1**, 01**1**, 10**1**, 11**1**)
- **Even Parity Check**: XOR of bits `data_in[1]`, `data_in[3]`, `data_in[5]`, and `data_in[7]`.
#### c2:
- Check all positions in `data_in` where the binary index has a 1 in the Second LSB position (0**1**0, 0**1**1, 1**1**0, 1**1**1)
- **Even Parity Check**: XOR of bits `data_in[2]`, `data_in[3]`, `data_in[6]`, and `data_in[7]` .
#### c1:
- Check all positions in `data_in` where the binary index has 1 in the most significant MSB position (**1**00, **1**01, **1**10, **1**11)
- **Even Parity Check**: XOR of bits `data_in[4]`, `data_in[5]`, `data_in[6]`, and `data_in[7]` .

#### Error Indication by {c1, c2, c3}:
- Result of **1** in any of the bits: Indicates an error (odd number of 1s).
- Result of **0** in any of the bits: No error (even number of 1s).

4.2 **Error Detection and Correction:**
- By combining the three error detection bits `(c1, c2, c3)`, the exact location of the erroneous bit in `data_in` can be identified.
- If an error is detected, the bit at the position indicated by `{c1, c2, c3}` is corrected.
- This operation will correct both data and parity bits. (The redundant bit is not corrected, nor is it part of `data_out`)
- If no error is detected, the data is passed through unchanged.

- **Case 1:** If `{c1, c2, c3} == 3'b000`, it points to position 0 of `data_in`, which is `data_in[0]`, the extra redundant bit. This means no error in data or parity bits in `data_in`, as indicated by the extra bit's position.
- **Case 2:** If `{c1, c2, c3} != 3'b000`, example: `{c1, c2, c3} == 3'b001`, it points to position **1** of `data_in`, making `data_in[1]` the error bit. In this case, the error bit must be **inverted** to correct the input.

4.3 **Output assignment:**
- After error correction, fetch the **data bits** from the decoded input, which holds the corrected data, and assign those **data bits** to the output port `data_out`. (`data_out` will contain corrected data bits at positions 7,6,5, and 3)

### 4. Timing and Synchronization
- This design is combinational and output should be immediately updated with a change in the input.

### 5. Constraints
- The design assumes that input data will contain only single-bit errors.