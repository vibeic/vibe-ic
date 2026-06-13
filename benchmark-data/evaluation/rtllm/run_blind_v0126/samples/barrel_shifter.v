module barrel_shifter (
    input  [7:0] in,
    input  [2:0] ctrl,
    output [7:0] out
);
    // 8-bit barrel shifter implemented as a left ROTATE in three mux stages.
    // ctrl[2] -> rotate by 4, ctrl[1] -> rotate by 2, ctrl[0] -> rotate by 1.
    // Each mux selects the rotated bit when its control bit is high, else the
    // (intermediate) original bit, so shifted-out MSBs wrap into the LSBs.
    wire [7:0] stage4; // after optional rotate by 4 (ctrl[2])
    wire [7:0] stage2; // after optional rotate by 2 (ctrl[1])

    // Stage 1: rotate left by 4 when ctrl[2] is high  -> out[i] = in[(i-4) mod 8]
    mux2X1 m4_7 (.a(in[7]), .b(in[3]), .sel(ctrl[2]), .out(stage4[7]));
    mux2X1 m4_6 (.a(in[6]), .b(in[2]), .sel(ctrl[2]), .out(stage4[6]));
    mux2X1 m4_5 (.a(in[5]), .b(in[1]), .sel(ctrl[2]), .out(stage4[5]));
    mux2X1 m4_4 (.a(in[4]), .b(in[0]), .sel(ctrl[2]), .out(stage4[4]));
    mux2X1 m4_3 (.a(in[3]), .b(in[7]), .sel(ctrl[2]), .out(stage4[3]));
    mux2X1 m4_2 (.a(in[2]), .b(in[6]), .sel(ctrl[2]), .out(stage4[2]));
    mux2X1 m4_1 (.a(in[1]), .b(in[5]), .sel(ctrl[2]), .out(stage4[1]));
    mux2X1 m4_0 (.a(in[0]), .b(in[4]), .sel(ctrl[2]), .out(stage4[0]));

    // Stage 2: rotate left by 2 when ctrl[1] is high
    mux2X1 m2_7 (.a(stage4[7]), .b(stage4[5]), .sel(ctrl[1]), .out(stage2[7]));
    mux2X1 m2_6 (.a(stage4[6]), .b(stage4[4]), .sel(ctrl[1]), .out(stage2[6]));
    mux2X1 m2_5 (.a(stage4[5]), .b(stage4[3]), .sel(ctrl[1]), .out(stage2[5]));
    mux2X1 m2_4 (.a(stage4[4]), .b(stage4[2]), .sel(ctrl[1]), .out(stage2[4]));
    mux2X1 m2_3 (.a(stage4[3]), .b(stage4[1]), .sel(ctrl[1]), .out(stage2[3]));
    mux2X1 m2_2 (.a(stage4[2]), .b(stage4[0]), .sel(ctrl[1]), .out(stage2[2]));
    mux2X1 m2_1 (.a(stage4[1]), .b(stage4[7]), .sel(ctrl[1]), .out(stage2[1]));
    mux2X1 m2_0 (.a(stage4[0]), .b(stage4[6]), .sel(ctrl[1]), .out(stage2[0]));

    // Stage 3: rotate left by 1 when ctrl[0] is high
    mux2X1 m1_7 (.a(stage2[7]), .b(stage2[6]), .sel(ctrl[0]), .out(out[7]));
    mux2X1 m1_6 (.a(stage2[6]), .b(stage2[5]), .sel(ctrl[0]), .out(out[6]));
    mux2X1 m1_5 (.a(stage2[5]), .b(stage2[4]), .sel(ctrl[0]), .out(out[5]));
    mux2X1 m1_4 (.a(stage2[4]), .b(stage2[3]), .sel(ctrl[0]), .out(out[4]));
    mux2X1 m1_3 (.a(stage2[3]), .b(stage2[2]), .sel(ctrl[0]), .out(out[3]));
    mux2X1 m1_2 (.a(stage2[2]), .b(stage2[1]), .sel(ctrl[0]), .out(out[2]));
    mux2X1 m1_1 (.a(stage2[1]), .b(stage2[0]), .sel(ctrl[0]), .out(out[1]));
    mux2X1 m1_0 (.a(stage2[0]), .b(stage2[7]), .sel(ctrl[0]), .out(out[0]));

endmodule

module mux2X1 (
    input  a,
    input  b,
    input  sel,
    output out
);
    assign out = sel ? b : a;
endmodule
