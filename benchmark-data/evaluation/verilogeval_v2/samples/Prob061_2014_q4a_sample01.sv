module TopModule (
    input  clk,
    input  w,
    input  R,
    input  E,
    input  L,
    output Q
);

    reg q_reg;

    always @(posedge clk) begin
        if (L)
            q_reg <= R;
        else if (E)
            q_reg <= w;
        else
            q_reg <= q_reg;
    end

    assign Q = q_reg;

endmodule
