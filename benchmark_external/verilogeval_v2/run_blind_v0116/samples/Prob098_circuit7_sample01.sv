module TopModule (
    input  clk,
    input  a,
    output q
);
    // Two-stage pipeline of inverted input: q[t] = ~a[t-2].
    reg r_reg = 1'b0;
    reg q_reg = 1'b0;

    always @(posedge clk) begin
        r_reg <= ~a;
        q_reg <= r_reg;
    end

    assign q = q_reg;
endmodule
