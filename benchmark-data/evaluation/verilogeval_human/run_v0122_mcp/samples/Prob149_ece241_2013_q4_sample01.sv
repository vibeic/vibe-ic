module TopModule (
  input            clk,
  input            reset,
  input      [3:1] s,
  output reg       fr3,
  output reg       fr2,
  output reg       fr1,
  output reg       dfr
);

  // Four water-level regions, lowest=0 .. highest=3, derived from sensor pattern.
  //   region 0: below s1      (s = 000)  -> fr1,fr2,fr3
  //   region 1: between s2,s1 (s = 001)  -> fr1,fr2
  //   region 2: between s3,s2 (s = 011)  -> fr1
  //   region 3: above s3      (s = 111)  -> none
  // dfr opens when the level just rose (current region > previous region).
  reg [1:0] prev;       // previous level region (state)
  reg [1:0] cur;        // current level region from sensors

  always @(*) begin
    case (s)
      3'b000:  cur = 2'd0;
      3'b001:  cur = 2'd1;
      3'b011:  cur = 2'd2;
      3'b111:  cur = 2'd3;
      default: cur = 2'd0;   // unreachable monotonic patterns
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      // water low for a long time: region 0, all four outputs asserted
      prev <= 2'd0;
      fr1  <= 1'b1;
      fr2  <= 1'b1;
      fr3  <= 1'b1;
      dfr  <= 1'b1;
    end else begin
      prev <= cur;
      // nominal valves by current region
      fr1  <= (cur <= 2'd2);            // open at regions 0,1,2
      fr2  <= (cur <= 2'd1);            // open at regions 0,1
      fr3  <= (cur == 2'd0);            // open at region 0
      // supplemental valve: level rose since last cycle
      dfr  <= (cur > prev);
    end
  end

endmodule
