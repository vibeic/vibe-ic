module TopModule (
  input clk,
  input reset,
  input [3:1] s,
  output reg fr3,
  output reg fr2,
  output reg fr1,
  output reg dfr
);
  // Current water level decoded from thermometer-coded sensors:
  //   level 0: no sensors          (below s1) -> fr1,fr2,fr3
  //   level 1: s1                  (s2..s1)   -> fr1,fr2
  //   level 2: s1,s2               (s3..s2)   -> fr1
  //   level 3: s1,s2,s3            (above s3) -> none
  // dfr asserted while the level is rising (current level higher than the
  // previous stable level).

  reg [1:0] level;       // last stable level
  reg [1:0] new_level;

  always @(*) begin
    case (s)
      3'b000: new_level = 2'd0;
      3'b001: new_level = 2'd1;   // s[1]
      3'b011: new_level = 2'd2;   // s[1],s[2]
      3'b111: new_level = 2'd3;   // s[1],s[2],s[3]
      default: new_level = level; // illegal pattern: hold
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      // equivalent to water having been low for a long time
      level <= 2'd0;
      fr1 <= 1'b1;
      fr2 <= 1'b1;
      fr3 <= 1'b1;
      dfr <= 1'b1;
    end else begin
      level <= new_level;
      // nominal flow by level
      fr1 <= (new_level <= 2'd2);
      fr2 <= (new_level <= 2'd1);
      fr3 <= (new_level == 2'd0);
      // supplemental flow: level rising vs previous level
      if (new_level > level)      dfr <= 1'b1;
      else if (new_level < level) dfr <= 1'b0;
      // equal: hold dfr
    end
  end
endmodule
