module TopModule(
    input  clk,
    input  enable,
    input  S,
    input  A,
    input  B,
    input  C,
    output Z
);
    reg [7:0] Q;
    // Shift register: S feeds Q[0], data moves toward higher index.
    always @(posedge clk) begin
        if (enable)
            Q <= {Q[6:0], S};
    end
    // 8:1 mux: address {A,B,C}, ABC=000 -> Q[0], 001 -> Q[1], ...
    assign Z = Q[{A, B, C}];
endmodule
