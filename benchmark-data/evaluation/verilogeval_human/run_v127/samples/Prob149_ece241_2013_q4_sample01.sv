module TopModule (
  input  clk,
  input  reset,
  input  [3:1] s,
  output reg fr3,
  output reg fr2,
  output reg fr1,
  output reg dfr
);

  // Hysteresis reservoir controller.
  // level = count of thermometer sensors asserted (0..3); non-thermometer
  // codes hold the previous level. dfr is a HELD flag: set on a level FALL,
  // cleared on a level RISE (anchored by the reset/boundary rows: bottom is
  // reached only by falling -> dfr=1, top only by rising -> dfr=0).
  reg [1:0] level;       // registered water level
  reg [1:0] new_level;   // combinational next level from sensors

  always @(*) begin
    case (s)
      3'b000:  new_level = 2'd0;  // none        -> below s1
      3'b001:  new_level = 2'd1;  // s1          -> between s2 and s1
      3'b011:  new_level = 2'd2;  // s1,s2       -> between s3 and s2
      3'b111:  new_level = 2'd3;  // s1,s2,s3    -> above s3
      default: new_level = level; // non-thermometer -> hold
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      level <= 2'd0;     // equivalent to having been low for a long time
      dfr   <= 1'b1;     // all four outputs asserted at the bottom
    end else begin
      level <= new_level;
      if (new_level > level)      dfr <= 1'b0;  // rising
      else if (new_level < level) dfr <= 1'b1;  // falling
      // equal: hold dfr
    end
  end

  // Moore decode of the registered level for the nominal flow valves.
  always @(*) begin
    fr1 = (level != 2'd3);  // asserted at levels 0,1,2
    fr2 = (level <= 2'd1);  // asserted at levels 0,1
    fr3 = (level == 2'd0);  // asserted at level 0 only
  end

endmodule
