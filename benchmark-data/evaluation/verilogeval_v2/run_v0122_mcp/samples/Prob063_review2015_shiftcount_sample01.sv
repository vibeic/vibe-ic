module TopModule (
    input  clk,
    input  shift_ena,
    input  count_ena,
    input  data,
    output reg [3:0] q
);

    initial q = 4'b0;   // deterministic power-up (t=0 reference expects 0)

    always @(posedge clk) begin
        if (shift_ena)
            q <= {q[2:0], data};   // shift in MSB-first
        else if (count_ena)
            q <= q - 4'd1;          // down counter
    end

endmodule
