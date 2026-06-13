// Reservoir flow controller with HYSTERESIS (history-dependent dfr).
//
// Thermometer-coded sensors s[3:1]:
//   s = 3'b111 : above s3            (top)
//   s = 3'b011 : between s3 and s2
//   s = 3'b001 : between s2 and s1
//   s = 3'b000 : below s1            (bottom)
//
// Nominal flow valves by level:
//   bottom 000 : fr1,fr2,fr3
//   001        : fr1,fr2
//   011        : fr1
//   top  111   : none
//
// dfr (Supplemental valve) opens when the water is RISING, i.e. the level
// previous to the last sensor change was LOWER than the current level.
// The two interior levels are therefore split into paired states encoding
// the direction of travel:
//   *_UP   : arrived from below (rising)  -> dfr = 1
//   *_DOWN : arrived from above (falling)  -> dfr = 0
// The bottom level is the maximum-flow state (all four outputs asserted) and
// is the synchronous-reset / "water low for a long time" anchor; the top
// level deasserts everything.
//
// Positive-edge clocked, Moore outputs (decoded from current state only).
module TopModule (
  input clk,
  input reset,
  input [3:1] s,
  output reg fr3,
  output reg fr2,
  output reg fr1,
  output reg dfr
);

  localparam BOT    = 3'd0; // s=000 max flow, all outputs (reset anchor)
  localparam MID_UP = 3'd1; // s=001 rising:  fr1,fr2,dfr
  localparam MID_DN = 3'd2; // s=001 falling: fr1,fr2
  localparam HI_UP  = 3'd3; // s=011 rising:  fr1,dfr
  localparam HI_DN  = 3'd4; // s=011 falling: fr1
  localparam TOP    = 3'd5; // s=111 none

  reg [2:0] state, next;

  // Next-state: decode the new level from the sensors; whether it is an
  // arrived-from-below (rising) or arrived-from-above (falling) state is
  // determined by comparing the new level to the level of the current state.
  always @(*) begin
    case (s)
      3'b000: next = BOT;                                  // bottom: always max-flow state
      3'b111: next = TOP;                                  // top: always no-flow state
      3'b001: begin                                        // interior level 001
        // rising if we came from a lower level (BOT)
        if (state == BOT)
          next = MID_UP;
        else if (state == MID_UP || state == MID_DN)
          next = state;                                    // no level change: hold direction
        else
          next = MID_DN;                                   // came from higher level (falling)
      end
      3'b011: begin                                        // interior level 011
        // rising if we came from a lower level (BOT/MID_*)
        if (state == HI_UP || state == HI_DN)
          next = state;                                    // no level change: hold direction
        else if (state == TOP)
          next = HI_DN;                                    // came from higher level (falling)
        else
          next = HI_UP;                                    // came from lower level (rising)
      end
      default: next = state;                               // illegal sensor code: hold
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= BOT;
    else
      state <= next;
  end

  // Moore output decode (function of current state only).
  always @(*) begin
    case (state)
      BOT:    begin fr3 = 1; fr2 = 1; fr1 = 1; dfr = 1; end
      MID_UP: begin fr3 = 0; fr2 = 1; fr1 = 1; dfr = 1; end
      MID_DN: begin fr3 = 0; fr2 = 1; fr1 = 1; dfr = 0; end
      HI_UP:  begin fr3 = 0; fr2 = 0; fr1 = 1; dfr = 1; end
      HI_DN:  begin fr3 = 0; fr2 = 0; fr1 = 1; dfr = 0; end
      TOP:    begin fr3 = 0; fr2 = 0; fr1 = 0; dfr = 0; end
      default:begin fr3 = 1; fr2 = 1; fr1 = 1; dfr = 1; end
    endcase
  end

endmodule
