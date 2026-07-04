// galois_encryption — GF(2^8) MixColumns-style encrypt/decrypt with a stored
// key, 3-clock output latency (i_valid -> o_valid), async active-low reset.
//   * input/output byte map: byte(r,c) = data[127 - 32*c - 8*r -: 8]
//   * encrypt: Re = M x data_in, then Re[r][c] ^= key_byte[r]
//   * decrypt: data_key = data_in ^ key (per row), then Rd = N x data_key
// GF(2^8) reduction polynomial m(x) = x^8+x^4+x^3+x+1 = 0x11B (0x1B truncated).
module galois_encryption #(
    parameter NBW_DATA = 128,
    parameter NBW_KEY  = 32
)(
    input  wire                  clk,
    input  wire                  rst_async_n,
    input  wire                  i_encrypt,
    input  wire                  i_valid,
    input  wire [NBW_DATA-1:0]   i_data,
    input  wire                  i_update_key,
    input  wire [NBW_KEY-1:0]    i_key,
    output reg                   o_valid,
    output reg  [NBW_DATA-1:0]   o_data
);
    // ---- GF(2^8) multiply ------------------------------------------------
    function automatic [7:0] gfmul(input [7:0] a, input [7:0] b);
        integer i;
        reg [7:0] aa, res;
        reg [7:0] bb;
        begin
            aa  = a;
            bb  = b;
            res = 8'h00;
            for (i = 0; i < 8; i = i + 1) begin
                if (bb[0]) res = res ^ aa;
                if (aa[7]) aa = (aa << 1) ^ 8'h1b;
                else       aa = (aa << 1);
                bb = bb >> 1;
            end
            gfmul = res;
        end
    endfunction

    // ---- stored key ------------------------------------------------------
    reg [NBW_KEY-1:0] key_reg;
    always @(posedge clk or negedge rst_async_n) begin
        if (!rst_async_n)      key_reg <= {NBW_KEY{1'b0}};
        else if (i_update_key) key_reg <= i_key;
    end

    // ---- pipeline stage 1 : capture inputs -------------------------------
    reg               s1_valid, s1_enc;
    reg [NBW_DATA-1:0] s1_data;

    // ---- combinational cipher of the stage-1 word ------------------------
    reg [7:0] din  [0:3][0:3];
    reg [7:0] keyb [0:3];
    reg [7:0] dk   [0:3][0:3];
    reg [7:0] mix  [0:3][0:3];
    reg [NBW_DATA-1:0] cipher_res;
    integer r, c;
    always @(*) begin
        keyb[0] = key_reg[31:24];
        keyb[1] = key_reg[23:16];
        keyb[2] = key_reg[15:8];
        keyb[3] = key_reg[7:0];
        for (r = 0; r < 4; r = r + 1)
            for (c = 0; c < 4; c = c + 1)
                din[r][c] = s1_data[(127 - 32*c - 8*r) -: 8];

        if (s1_enc) begin
            // Re = M x data_in, M = [[2,3,1,1],[1,2,3,1],[1,1,2,3],[3,1,1,2]]
            for (c = 0; c < 4; c = c + 1) begin
                mix[0][c] = gfmul(din[0][c],8'h02) ^ gfmul(din[1][c],8'h03)
                          ^ din[2][c]              ^ din[3][c];
                mix[1][c] = din[0][c]              ^ gfmul(din[1][c],8'h02)
                          ^ gfmul(din[2][c],8'h03) ^ din[3][c];
                mix[2][c] = din[0][c]              ^ din[1][c]
                          ^ gfmul(din[2][c],8'h02) ^ gfmul(din[3][c],8'h03);
                mix[3][c] = gfmul(din[0][c],8'h03) ^ din[1][c]
                          ^ din[2][c]              ^ gfmul(din[3][c],8'h02);
            end
            // XOR key byte into every column of its row
            for (r = 0; r < 4; r = r + 1)
                for (c = 0; c < 4; c = c + 1)
                    mix[r][c] = mix[r][c] ^ keyb[r];
        end else begin
            // decrypt: data_key = data ^ key (per row) ...
            for (r = 0; r < 4; r = r + 1)
                for (c = 0; c < 4; c = c + 1)
                    dk[r][c] = din[r][c] ^ keyb[r];
            // ... then Rd = N x data_key,
            // N = [[0e,0b,0d,09],[09,0e,0b,0d],[0d,09,0e,0b],[0b,0d,09,0e]]
            for (c = 0; c < 4; c = c + 1) begin
                mix[0][c] = gfmul(dk[0][c],8'h0e) ^ gfmul(dk[1][c],8'h0b)
                          ^ gfmul(dk[2][c],8'h0d) ^ gfmul(dk[3][c],8'h09);
                mix[1][c] = gfmul(dk[0][c],8'h09) ^ gfmul(dk[1][c],8'h0e)
                          ^ gfmul(dk[2][c],8'h0b) ^ gfmul(dk[3][c],8'h0d);
                mix[2][c] = gfmul(dk[0][c],8'h0d) ^ gfmul(dk[1][c],8'h09)
                          ^ gfmul(dk[2][c],8'h0e) ^ gfmul(dk[3][c],8'h0b);
                mix[3][c] = gfmul(dk[0][c],8'h0b) ^ gfmul(dk[1][c],8'h0d)
                          ^ gfmul(dk[2][c],8'h09) ^ gfmul(dk[3][c],8'h0e);
            end
        end

        cipher_res = {NBW_DATA{1'b0}};
        for (r = 0; r < 4; r = r + 1)
            for (c = 0; c < 4; c = c + 1)
                cipher_res[(127 - 32*c - 8*r) -: 8] = mix[r][c];
    end

    // ---- pipeline stage 2 : register the cipher result -------------------
    reg               s2_valid;
    reg [NBW_DATA-1:0] s2_res;

    always @(posedge clk or negedge rst_async_n) begin
        if (!rst_async_n) begin
            s1_valid <= 1'b0; s1_enc <= 1'b0; s1_data <= {NBW_DATA{1'b0}};
            s2_valid <= 1'b0; s2_res <= {NBW_DATA{1'b0}};
            o_valid  <= 1'b0; o_data <= {NBW_DATA{1'b0}};
        end else begin
            // stage 1
            s1_valid <= i_valid;
            s1_enc   <= i_encrypt;
            s1_data  <= i_data;
            // stage 2
            s2_valid <= s1_valid;
            s2_res   <= cipher_res;
            // stage 3 (outputs) — 3-cycle latency from i_valid to o_valid
            o_valid  <= s2_valid;
            o_data   <= s2_valid ? s2_res : {NBW_DATA{1'b0}};
        end
    end
endmodule
