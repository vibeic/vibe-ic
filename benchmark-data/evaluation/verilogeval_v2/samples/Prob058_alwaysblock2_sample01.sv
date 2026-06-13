module TopModule (
    input  clk,
    input  a,
    input  b,
    output out_assign,
    output out_always_comb,
    output reg out_always_ff
);

    assign out_assign = a ^ b;

    reg comb;
    always @(*) begin
        comb = a ^ b;
    end
    assign out_always_comb = comb;

    always @(posedge clk) begin
        out_always_ff <= a ^ b;
    end

endmodule
