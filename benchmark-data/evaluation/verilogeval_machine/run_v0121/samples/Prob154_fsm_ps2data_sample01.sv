module TopModule (
  input clk,
  input [7:0] in,
  input reset,    // synchronous reset to BYTE1
  output [23:0] out_bytes,
  output done
);
  localparam BYTE1=2'd0, BYTE2=2'd1, BYTE3=2'd2, DONE=2'd3;
  reg [1:0] state, next;
  reg [23:0] shifted = 24'd0;

  // next-state logic
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

  // datapath: shift the 8-bit input into a 24-bit register each cycle
  always @(posedge clk) begin
    shifted <= {shifted[15:0], in};
  end

  assign done      = (state == DONE);
  assign out_bytes = done ? shifted : 24'h0;
endmodule
