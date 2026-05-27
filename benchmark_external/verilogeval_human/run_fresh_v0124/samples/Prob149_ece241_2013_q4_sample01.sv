module TopModule (
  input clk,
  input reset,
  input [3:1] s,
  output reg fr3,
  output reg fr2,
  output reg fr1,
  output reg dfr
);

  // Map monotonic sensor pattern to a level band index 0..3.
  // 000 -> 0 (below s1, max flow), 001 -> 1, 011 -> 2, 111 -> 3 (above s3).
  function [1:0] band;
    input [3:1] sv;
    begin
      if      (sv[3]) band = 2'd3; // s1,s2,s3
      else if (sv[2]) band = 2'd2; // s1,s2
      else if (sv[1]) band = 2'd1; // s1
      else            band = 2'd0; // none
    end
  endfunction

  reg [1:0] prev;     // previous level band
  wire [1:0] cur = band(s);

  always @(posedge clk) begin
    if (reset) begin
      prev <= 2'd0;   // low for a long time
      dfr  <= 1'b1;   // supplemental asserted at max flow
    end else begin
      if (cur != prev) begin
        // dfr asserted when level dropped (water went down -> boost flow)
        dfr <= (cur < prev) ? 1'b1 : 1'b0;
      end
      prev <= cur;
    end
  end

  // Nominal flow valves are a pure function of the current band.
  always @(*) begin
    case (cur)
      2'd3: begin fr1 = 1'b0; fr2 = 1'b0; fr3 = 1'b0; end // above s3
      2'd2: begin fr1 = 1'b1; fr2 = 1'b0; fr3 = 1'b0; end // between s3 and s2
      2'd1: begin fr1 = 1'b1; fr2 = 1'b1; fr3 = 1'b0; end // between s2 and s1
      default: begin fr1 = 1'b1; fr2 = 1'b1; fr3 = 1'b1; end // below s1
    endcase
  end

endmodule
