module TopModule (
    input  clk,
    input  L,
    input  q_in,
    input  r_in,
    output Q
);
    reg Q_reg;
    always @(posedge clk) begin
        Q_reg <= L ? r_in : q_in;
    end
    assign Q = Q_reg;
endmodule
