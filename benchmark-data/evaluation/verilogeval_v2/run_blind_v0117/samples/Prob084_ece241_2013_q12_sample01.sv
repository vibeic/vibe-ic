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
    // Shift register: S feeds Q[0]; on enable each FF takes the value below it.
    always @(posedge clk) begin
        if (enable) begin
            Q[0] <= S;
            Q[7:1] <= Q[6:0];
        end
    end
    // 8x1 read mux addressed by {A,B,C} (ABC=000 -> Q[0]).
    assign Z = Q[{A, B, C}];
endmodule
