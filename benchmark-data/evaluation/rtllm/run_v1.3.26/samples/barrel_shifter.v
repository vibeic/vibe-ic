module mux2X1(
    input  wire a,
    input  wire b,
    input  wire sel,
    output wire y
);
assign y = sel ? b : a;
endmodule


module barrel_shifter(
    input  wire [7:0] in,
    input  wire [2:0] ctrl,
    output wire [7:0] out
);

wire [7:0] stage1, stage2, stage3;
wire [7:0] shifted4 = in     >> 4;
wire [7:0] shifted2 = stage1 >> 2;
wire [7:0] shifted1 = stage2 >> 1;

genvar i;

generate
    for (i = 0; i < 8; i = i + 1) begin : STAGE1
        mux2X1 m1 (.a(in[i]),     .b(shifted4[i]), .sel(ctrl[2]), .y(stage1[i]));
    end
    for (i = 0; i < 8; i = i + 1) begin : STAGE2
        mux2X1 m2 (.a(stage1[i]), .b(shifted2[i]), .sel(ctrl[1]), .y(stage2[i]));
    end
    for (i = 0; i < 8; i = i + 1) begin : STAGE3
        mux2X1 m3 (.a(stage2[i]), .b(shifted1[i]), .sel(ctrl[0]), .y(stage3[i]));
    end
endgenerate

assign out = stage3;

endmodule
