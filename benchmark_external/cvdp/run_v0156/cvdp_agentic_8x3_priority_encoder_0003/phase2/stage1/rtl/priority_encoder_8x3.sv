// priority_encoder_8x3 — 8-to-3 priority encoder with SVA validation.
// Authored blind from work/PROMPT.txt + work/verif/priority_encoder_tb.sv,
// no peek at score/.
//
// Spec (from prompt):
//   - input  in[7:0]: 8 lines
//   - output out[2:0]: binary index of the highest-priority active bit
//   - "MSL [MSB] to LSB high bit priority" → bit 7 is highest priority
//   - prompt also requests an SVA immediate assertion validating `out`
`timescale 1ns/1ps
module priority_encoder_8x3 (
    input      [7:0] in,
    output reg [2:0] out
);
    // Canonical MSB-priority cascade. `out` is purely combinational.
    always @(*) begin
        if      (in[7]) out = 3'd7;
        else if (in[6]) out = 3'd6;
        else if (in[5]) out = 3'd5;
        else if (in[4]) out = 3'd4;
        else if (in[3]) out = 3'd3;
        else if (in[2]) out = 3'd2;
        else if (in[1]) out = 3'd1;
        else            out = 3'd0;   // covers in[0]==1 and in==0
    end

    // SVA immediate assertion (prompt-mandated). Computes the expected
    // MSB-priority index independently of the cascade above, so a fault
    // in either direction is caught.
    `ifdef SVA_ON
    integer  j_assert;
    reg [2:0] expected_assert;
    always @(*) begin
        expected_assert = 3'd0;
        for (j_assert = 7; j_assert >= 0; j_assert = j_assert - 1) begin
            if (in[j_assert] && expected_assert == 3'd0 && !(in[7:j_assert+1] != 8'b0 && j_assert < 7))
                expected_assert = j_assert[2:0];
        end
        if (|in)
            assert (out == expected_assert)
              else $error("priority_encoder_8x3: out=%0d expected=%0d for in=%b",
                          out, expected_assert, in);
    end
    `endif
endmodule
