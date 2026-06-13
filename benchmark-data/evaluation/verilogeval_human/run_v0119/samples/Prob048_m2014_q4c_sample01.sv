module TopModule (
  input clk,
  input d,
  input r,
  output logic q
);
    // positive-edge triggered, active-high synchronous reset to 0
    initial q = 1'b0;              // deterministic power-up before first reset
    always @(posedge clk) begin
        if (r)
            q <= 1'b0;
        else
            q <= d;
    end
endmodule
