module TopModule (
  input clk,
  input [7:0] in,
  input reset,
  output [23:0] out_bytes,
  output done
);

  localparam BYTE1 = 2'd0, BYTE2 = 2'd1, BYTE3 = 2'd2, DONE = 2'd3;
  reg [1:0] state, next;
  reg [23:0] shift_reg;

  // Next-state logic
  always @(*) begin
    case (state)
      BYTE1: next = in[2] ? BYTE2 : BYTE1;
      BYTE2: next = BYTE3;
      BYTE3: next = DONE;
      DONE:  next = in[2] ? BYTE2 : BYTE1;
      default: next = BYTE1;
    endcase
  end

  // State register (synchronous reset)
  always @(posedge clk) begin
    if (reset)
      state <= BYTE1;
    else
      state <= next;
  end

  // Datapath: shift the 8-bit input into the 24-bit register each cycle
  always @(posedge clk) begin
    shift_reg <= {shift_reg[15:0], in};
  end

  assign done      = (state == DONE);
  assign out_bytes = (state == DONE) ? shift_reg : 24'b0;

endmodule
