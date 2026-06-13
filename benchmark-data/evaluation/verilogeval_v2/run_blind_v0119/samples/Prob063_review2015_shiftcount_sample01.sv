module TopModule(
    input  clk,
    input  shift_ena,
    input  count_ena,
    input  data,
    output reg [3:0] q = 4'b0
);
    always @(posedge clk) begin
        if (shift_ena)
            q <= {q[2:0], data};   // MSB-first shift-in
        else if (count_ena)
            q <= q - 4'd1;          // down counter
    end
endmodule
