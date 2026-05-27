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
    // S feeds Q[0]; on enable shift up so each FF passes its value on.
    always @(posedge clk) begin
        if (enable)
            Q <= {Q[6:0], S};
    end
    // Random-access read: address {A,B,C}, ABC=000 -> Q[0].
    assign Z = Q[{A, B, C}];
endmodule
