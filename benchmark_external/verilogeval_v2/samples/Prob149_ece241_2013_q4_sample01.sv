module TopModule (
  input  clk,
  input  reset,
  input  [2:0] s,
  output fr2,
  output fr1,
  output fr0,
  output dfr
);

  // Decode current water level from the (thermometer-coded) sensors:
  //   111 -> 3 (above s2), 011 -> 2, 001 -> 1, 000 -> 0 (below s0)
  function [1:0] level;
    input [2:0] sv;
    begin
      case (sv)
        3'b111:  level = 2'd3;
        3'b011:  level = 2'd2;
        3'b001:  level = 2'd1;
        default: level = 2'd0;   // 000
      endcase
    end
  endfunction

  reg [1:0] cur;     // current level (registered)
  reg       rising;  // 1 if the last level change was upward (water rose)

  wire [1:0] newlvl = level(s);

  always @(posedge clk) begin
    if (reset) begin
      cur    <= 2'd0;   // low for a long time
      rising <= 1'b1;   // all four outputs asserted (dfr=1)
    end else begin
      if (newlvl > cur)      rising <= 1'b1;
      else if (newlvl < cur) rising <= 1'b0;
      // unchanged -> hold rising
      cur <= newlvl;
    end
  end

  // Nominal flow outputs based on current level
  assign fr0 = (cur != 2'd3);          // asserted for all but the top level
  assign fr1 = (cur <= 2'd1);
  assign fr2 = (cur == 2'd0);

  // Supplemental valve: only when water is rising and not at the top level
  assign dfr = rising && (cur != 2'd3);

endmodule
