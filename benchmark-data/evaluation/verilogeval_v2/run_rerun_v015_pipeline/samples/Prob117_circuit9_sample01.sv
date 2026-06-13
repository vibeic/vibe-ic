module TopModule (
    input        clk,
    input        a,
    output [2:0] q
);
    reg [2:0] q_reg;
    always @(posedge clk) begin
        if (a)
            q_reg <= 3'd4;                       // a=1 loads 4
        else
            q_reg <= (q_reg == 3'd6) ? 3'd0 : q_reg + 3'd1; // count 0..6 mod 7
    end
    assign q = q_reg;
endmodule
