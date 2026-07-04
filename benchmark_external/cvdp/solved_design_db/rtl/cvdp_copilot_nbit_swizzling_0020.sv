module nbit_swizzling #(parameter DATA_WIDTH = 64)(
    input [DATA_WIDTH-1:0] data_in,                                         // Input data of size DATA_WIDTH
    input [1:0] sel,                                                        //  2-bit selection signal
    output reg [DATA_WIDTH:0] data_out,                                     // Output data of size DATA_WIDTH
    output reg [DATA_WIDTH + $clog2(DATA_WIDTH):0] ecc_out                  // Hamming ECC encoded output
);

localparam PARITY_BITS = $clog2(DATA_WIDTH + $clog2(DATA_WIDTH) + 1);
localparam CODE_LEN    = DATA_WIDTH + PARITY_BITS;

integer i;
wire parity_bit;


assign parity_bit = ^data_in;

always @(*) begin
    case(sel)
        2'b00: begin
            for (i = 0; i < DATA_WIDTH; i = i + 1) begin
                data_out[i] = data_in[DATA_WIDTH-1-i];
            end
            data_out[DATA_WIDTH] = parity_bit;
        end

        2'b01: begin
            for (i = 0; i < DATA_WIDTH/2; i = i + 1) begin
                data_out[i]                = data_in[DATA_WIDTH/2-1-i];
                data_out[DATA_WIDTH/2 + i] = data_in[DATA_WIDTH-1-i];
            end
            data_out[DATA_WIDTH] = parity_bit;
        end

        2'b10: begin
            for (i = 0; i < DATA_WIDTH/4; i = i + 1) begin
                data_out[i] = data_in[DATA_WIDTH/4-1-i];
                data_out[DATA_WIDTH/4 + i]   = data_in[DATA_WIDTH/2-1-i];
                data_out[DATA_WIDTH/2 + i]   = data_in[3*DATA_WIDTH/4-1-i];
                data_out[3*DATA_WIDTH/4 + i] = data_in[DATA_WIDTH-1-i];
            end
            data_out[DATA_WIDTH] = parity_bit;
        end

        2'b11: begin
            for (i = 0; i < DATA_WIDTH/8; i = i + 1) begin
                data_out[i]                  = data_in[DATA_WIDTH/8-1-i];
                data_out[DATA_WIDTH/8 + i]   = data_in[DATA_WIDTH/4-1-i];
                data_out[DATA_WIDTH/4 + i]   = data_in[3*DATA_WIDTH/8-1-i];
                data_out[3*DATA_WIDTH/8 + i] = data_in[DATA_WIDTH/2-1-i];
                data_out[DATA_WIDTH/2 + i]   = data_in[5*DATA_WIDTH/8-1-i];
                data_out[5*DATA_WIDTH/8 + i] = data_in[3*DATA_WIDTH/4-1-i];
                data_out[3*DATA_WIDTH/4 + i] = data_in[7*DATA_WIDTH/8-1-i];
                data_out[7*DATA_WIDTH/8 + i] = data_in[DATA_WIDTH-1-i];
            end
            data_out[DATA_WIDTH] = parity_bit;
        end
        default: begin
            data_out = data_in;
            data_out[DATA_WIDTH] = parity_bit;
        end
    endcase
end

// ---------------------------------------------------------------------------
// Hamming ECC generation
//  - Positions are 1-indexed (1 .. CODE_LEN).
//  - Positions that are a power of two (1,2,4,8,...) hold parity bits.
//  - The remaining positions are filled, in order, with the bits of data_in.
//  - Parity bit at position 2^k is the even parity (XOR) of every position
//    whose 1-indexed value has bit k set.
//  - ecc_out[pos-1] holds the codeword bit for position pos.
// ---------------------------------------------------------------------------
integer pos;
integer didx;
integer k;
integer ppos;
reg      p;
reg [CODE_LEN-1:0] cw;

always @(*) begin
    cw   = {CODE_LEN{1'b0}};
    didx = 0;
    // Place the data bits at the non-power-of-two positions.
    for (pos = 1; pos <= CODE_LEN; pos = pos + 1) begin
        if ((pos & (pos - 1)) != 0) begin
            cw[pos-1] = data_in[didx];
            didx = didx + 1;
        end
    end
    // Compute every parity bit (even parity over its covered positions).
    for (k = 0; k < PARITY_BITS; k = k + 1) begin
        ppos = (1 << k);
        p    = 1'b0;
        for (pos = 1; pos <= CODE_LEN; pos = pos + 1) begin
            if ((pos != ppos) && (((pos >> k) & 1) == 1))
                p = p ^ cw[pos-1];
        end
        cw[ppos-1] = p;
    end
    ecc_out = cw;
end

endmodule
