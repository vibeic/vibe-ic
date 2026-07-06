Design the System Verilog module `gf_multiplier` for a 4-bit Galois Field Multiplier (GF(2<sup>4</sup>)) by utilizing the irreducible polynomial **x<sup>4</sup> + x + 1**. The multiplication should be operated between two 4-bit values to result in a 4-bit product output.

### Interface

#### Inputs:

- **A ([3:0], 4-bit)**: The multiplicand. It should contain a 4-bit value between 0000 and 1111.
- **B ([3:0], 4-bit)**: The multiplier. It should contain a 4-bit value between 0000 and 1111.

#### Output:

- **result ([3:0], 4-bit)**: The product of the two input values using the GF multiplication algorithm.

## Design Specification:

- This design has to ensure that any overflow occurring during the multiplication process is reduced by the irreducible polynomial, ensuring the result remains within 4 bits.
- The design should follow combinational logic and produce the multiplication output whenever the input changes
- **Registers**: A set of 4-bit internal registers are to be used to hold the multiplicand and the intermediate result.
- **Polynomial Reduction**: The irreducible polynomial **x<sup>4</sup> + x + 1** (represented as `5'b10011`) has to be used for polynomial reduction in case of overflow during the multiplication process.
- For each bit of the multiplier, the multiplicand has to be conditionally XORed with the result and shifted to left by one bit. If overflow occurs, polynomial reduction is performed using the irreducible polynomial.

The algorithm of the GF multiplier to be followed in the RTL design is given below:

### Algorithm:

```
1. Initialize `result` = 0
2. Set multiplicand = `A`
3. For each bit (i) of the multiplier `B` (from LSB to MSB):
   - If the bit (i) of `B` is 1, `result` = `result` XOR multiplicand
      - Shift multiplicand to the left by 1 bit
      - If the MSB of the multiplicand is 1 after shifting, perform polynomial reduction:
         multiplicand = multiplicand XOR binary representation of irreducible polynomial (5'b10011)
   - else if the bit (i) of B is 0, result remains the same as `result` = `result` XOR 0
     - Shift multiplicand to the left by 1 bit
     - If the MSB of the multiplicand is 1 after shifting, perform polynomial reduction:
         multiplicand = multiplicand XOR binary representation of irreducible polynomial (5'b10011)
4. Return the final result
```

### Example computation:

Assume A = 3 (`0011`) and B = 7 (`0111`)

1. **Initialization**:
   - `A` = 3 (`0011`)
   - `B` = 7 (`0111`)
   - `result` = 0
2. **Iteration 1** (Multiplier's LSB is 1, index B[0]):
   - `result` = 0 XOR `0011` = `0011`
   - Shift multiplicand: `0011` << 1 = `0110` (No polynomial reduction as MSB is 0)
3. **Iteration 2** (Next bit is 1, index B[1]):
   - `result` = `0011` XOR `0110` = `0101`
   - Shift multiplicand: `0110` << 1 = `1100` (No polynomial reduction as MSB is 0)
4. **Iteration 3** (Next bit is 1, index B[2]):
   - `result` = `0101` XOR `1100` = `1001`
   - Shift multiplicand: `1100` << 1 = `11000` (Perform polynomial reduction as MSB is 1)
   - Polynomial reduction: `11000` XOR `10011` = `01011` (Multiplicand becomes `1011`)
5. **Iteration 4** (Next bit is 0, index B[3]):
   - `result` = `1001` XOR 0 = `1001`
6. **Final Step**:
   - The final result of GF multiplication after all iterations is `1001`, which is 9 in decimal.