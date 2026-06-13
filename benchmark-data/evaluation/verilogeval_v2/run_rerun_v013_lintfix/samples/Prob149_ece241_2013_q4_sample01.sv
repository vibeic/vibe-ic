module TopModule (
  input        clk,
  input        reset,
  input  [2:0] s,
  output       fr2,
  output       fr1,
  output       fr0,
  output       dfr
);

  // region: 0 = below s0, 1 = between s0/s1, 2 = between s1/s2, 3 = above s2
  reg [1:0] level;     // current water region
  reg       dfr_r;

  reg [1:0] new_level;
  always @(*) begin
    case (s)
      3'b000: new_level = 2'd0;
      3'b001: new_level = 2'd1;
      3'b011: new_level = 2'd2;
      3'b111: new_level = 2'd3;
      default: new_level = level; // unexpected sensor pattern: hold
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      level <= 2'd0;     // water low for a long time
      dfr_r <= 1'b1;     // supplemental open at reset
    end else begin
      level <= new_level;
      if (new_level > level)
        dfr_r <= 1'b1;   // previous level lower than current -> open supplemental
      else if (new_level < level)
        dfr_r <= 1'b0;   // previous level higher than current -> close supplemental
      // equal: hold dfr
    end
  end

  // nominal flow outputs from current level
  assign fr0 = (level <= 2'd2);            // asserted in regions 0,1,2 (not above s2)
  assign fr1 = (level <= 2'd1);            // asserted in regions 0,1
  assign fr2 = (level == 2'd0);            // asserted only below s0
  assign dfr = dfr_r;

endmodule
