module TopModule (
    input  clk,
    input  enable,
    input  S,
    input  A,
    input  B,
    input  C,
    output Z
);
    reg [7:0] Q;
    // Shift register: S feeds Q[0]; on shift, Q[0]->Q[1]->...->Q[7].
    always @(posedge clk) begin
        if (enable)
            Q <= {Q[6:0], S};
    end
    // Z is Q selected by index {A,B,C}: ABC=000 -> Q[0], 001 -> Q[1], ...
    assign Z = Q[{A, B, C}];
endmodule
