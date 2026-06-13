module TopModule (
  input         clk,
  input  [7:0]  in,
  input         reset,
  output [23:0] out_bytes,
  output        done
);

  localparam BYTE1 = 2'd0,  // search for first byte (in[3]==1)
             BYTE2 = 2'd1,
             BYTE3 = 2'd2,
             DONE  = 2'd3;  // message complete: assert done, out_bytes valid

  reg [1:0] state, next;
  reg [7:0] b1, b2, b3;     // captured message bytes

  always @(*) begin
    case (state)
      BYTE1: next = in[3] ? BYTE2 : BYTE1;
      BYTE2: next = BYTE3;
      BYTE3: next = DONE;
      DONE:  next = in[3] ? BYTE2 : BYTE1;   // begin next message if start seen
      default: next = BYTE1;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= BYTE1;
    end else begin
      state <= next;
      // capture bytes as they arrive
      if (state == BYTE1 && in[3]) b1 <= in;
      if (state == DONE   && in[3]) b1 <= in;   // first byte of next message
      if (state == BYTE2) b2 <= in;
      if (state == BYTE3) b3 <= in;
    end
  end

  assign done      = (state == DONE);
  assign out_bytes = {b1, b2, b3};

endmodule
