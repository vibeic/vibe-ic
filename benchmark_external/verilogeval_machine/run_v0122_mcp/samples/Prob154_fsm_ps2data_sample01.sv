// Prob154_fsm_ps2data — PS/2 3-byte packet receiver FSM.
// States BYTE1..BYTE3,DONE. sync reset -> BYTE1. Shift in each cycle.
// out_bytes valid (= captured 24-bit packet) when done (state==DONE).
module TopModule (
  input clk,
  input [7:0] in,
  input reset,
  output [23:0] out_bytes,
  output done
);

  localparam BYTE1=2'd0, BYTE2=2'd1, BYTE3=2'd2, DONE=2'd3;
  reg [1:0] state, next;
  reg [23:0] shiftreg;

  always @(*) begin
    case (state)
      BYTE1: next = in[3] ? BYTE2 : BYTE1;
      BYTE2: next = BYTE3;
      BYTE3: next = DONE;
      DONE:  next = in[3] ? BYTE2 : BYTE1;
      default: next = BYTE1;
    endcase
  end

  always @(posedge clk) begin
    if (reset) state <= BYTE1;
    else       state <= next;
  end

  always @(posedge clk)
    shiftreg <= {shiftreg[15:0], in};

  assign done      = (state == DONE);
  assign out_bytes = done ? shiftreg : 24'h0;

endmodule
