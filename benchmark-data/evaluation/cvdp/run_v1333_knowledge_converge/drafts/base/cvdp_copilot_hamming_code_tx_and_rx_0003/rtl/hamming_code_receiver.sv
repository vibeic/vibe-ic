// hamming_code_receiver
// Combinational Hamming (7,4) receiver operating on data_in[7:1]
// with data_in[0] as an extra redundant bit.
// Detects and corrects single-bit errors using even-parity syndrome bits.
module hamming_code_receiver (
    input  wire [7:0] data_in,
    output wire [3:0] data_out
);

    // Even-parity syndrome bits.
    // c3: XOR of positions with LSB=1   -> indices 1,3,5,7
    // c2: XOR of positions with bit1=1  -> indices 2,3,6,7
    // c1: XOR of positions with MSB=1   -> indices 4,5,6,7
    wire c3 = data_in[1] ^ data_in[3] ^ data_in[5] ^ data_in[7];
    wire c2 = data_in[2] ^ data_in[3] ^ data_in[6] ^ data_in[7];
    wire c1 = data_in[4] ^ data_in[5] ^ data_in[6] ^ data_in[7];

    // Syndrome value = {c1, c2, c3}, points to the erroneous bit index.
    // 0 => no error (points at the redundant bit position 0).
    wire [2:0] syndrome = {c1, c2, c3};

    // Correct the indicated bit (if any) by inverting it.
    reg [7:0] corrected;
    integer i;
    always @(*) begin
        corrected = data_in;
        if (syndrome != 3'b000) begin
            corrected[syndrome] = ~data_in[syndrome];
        end
    end

    // Data bits reside at non-power-of-2 positions: 3,5,6,7.
    // data_out packs them MSB-first as {pos7, pos6, pos5, pos3}.
    assign data_out = {corrected[7], corrected[6], corrected[5], corrected[3]};

endmodule
