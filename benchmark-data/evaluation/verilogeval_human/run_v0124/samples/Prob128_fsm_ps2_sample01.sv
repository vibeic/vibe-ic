module TopModule (
  input clk,
  input [7:0] in,
  input reset,
  output done
);

  // States: search for byte1 (in[3]=1), then byte2, byte3, then DONE.
  localparam S_BYTE1 = 2'd0,  // waiting for first byte (in[3]=1)
             S_BYTE2 = 2'd1,  // received byte1, waiting byte2
             S_BYTE3 = 2'd2,  // received byte2, waiting byte3
             S_DONE  = 2'd3;  // byte3 received, signal done this cycle

  reg [1:0] state, next;

  always @(*) begin
    case (state)
      S_BYTE1: next = in[3] ? S_BYTE2 : S_BYTE1;
      S_BYTE2: next = S_BYTE3;
      S_BYTE3: next = S_DONE;
      S_DONE:  next = in[3] ? S_BYTE2 : S_BYTE1;
      default: next = S_BYTE1;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= S_BYTE1;
    else
      state <= next;
  end

  assign done = (state == S_DONE);

endmodule
