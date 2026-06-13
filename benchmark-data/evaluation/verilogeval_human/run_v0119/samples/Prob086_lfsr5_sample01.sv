module TopModule (
  input clk,
  input reset,
  output reg [4:0] q
);
    always @(posedge clk) begin
        if (reset)
            q <= 5'h1;
        else begin
            // Galois LFSR shifting right; taps at positions 5 and 3 XOR q[0]
            q[4] <= q[0];
            q[3] <= q[4];
            q[2] <= q[3] ^ q[0];
            q[1] <= q[2];
            q[0] <= q[1];
        end
    end
endmodule
