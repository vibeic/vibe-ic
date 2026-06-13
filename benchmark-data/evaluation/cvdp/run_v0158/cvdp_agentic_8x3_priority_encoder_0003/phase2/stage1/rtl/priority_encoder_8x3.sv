// priority_encoder_8x3 — 8-to-3 MSB-priority encoder, blind from prompt.
// Re-author on v0.1.58.
`timescale 1ns/1ps
module priority_encoder_8x3 (
    input      [7:0] in,
    output reg [2:0] out
);
    always @(*) begin
        if      (in[7]) out = 3'd7;
        else if (in[6]) out = 3'd6;
        else if (in[5]) out = 3'd5;
        else if (in[4]) out = 3'd4;
        else if (in[3]) out = 3'd3;
        else if (in[2]) out = 3'd2;
        else if (in[1]) out = 3'd1;
        else            out = 3'd0;
    end
endmodule
