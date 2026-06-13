module TopModule (
  input clk,
  input load,
  input [511:0] data,
  output reg [511:0] q
);

  integer i;
  reg [511:0] qn;
  reg left, center, right;

  always @(*) begin
    for (i = 0; i < 512; i = i + 1) begin
      center = q[i];
      left   = (i == 511) ? 1'b0 : q[i+1];
      right  = (i == 0)   ? 1'b0 : q[i-1];
      // Rule 110: next is 0 for patterns 111, 100, 000
      case ({left, center, right})
        3'b111: qn[i] = 1'b0;
        3'b110: qn[i] = 1'b1;
        3'b101: qn[i] = 1'b1;
        3'b100: qn[i] = 1'b0;
        3'b011: qn[i] = 1'b1;
        3'b010: qn[i] = 1'b1;
        3'b001: qn[i] = 1'b1;
        3'b000: qn[i] = 1'b0;
        default: qn[i] = 1'b0;
      endcase
    end
  end

  always @(posedge clk) begin
    if (load)
      q <= data;
    else
      q <= qn;
  end


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
