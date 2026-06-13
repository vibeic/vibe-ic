module TopModule (
  input clk,
  input d,
  input ar,
  output logic q
);
    // positive-edge triggered, asynchronous reset ar to 0
    initial q = 1'b0;             // deterministic power-up
    always @(posedge clk or posedge ar) begin
        if (ar)
            q <= 1'b0;
        else
            q <= d;
    end
endmodule
