module TopModule (
  input clk,
  input [7:0] in,
  input reset,
  output [23:0] out_bytes,
  output done
);

  localparam BYTE1 = 2'd0, BYTE2 = 2'd1, BYTE3 = 2'd2, DONE = 2'd3;
  reg [1:0] state, next;
  reg [23:0] data;

  always @(*) begin
    case (state)
      BYTE1: next = in[3] ? BYTE2 : BYTE1;  // wait for start byte (in[3]=1)
      BYTE2: next = BYTE3;
      BYTE3: next = DONE;
      DONE:  next = in[3] ? BYTE2 : BYTE1;  // next message may start immediately
      default: next = BYTE1;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= BYTE1;
      data  <= 24'd0;
    end else begin
      state <= next;
      // capture bytes into the 24-bit message (byte1 is MSB)
      case (state)
        BYTE1: if (in[3]) data[23:16] <= in;
        BYTE2: data[15:8] <= in;
        BYTE3: data[7:0]  <= in;
        DONE:  if (in[3]) data[23:16] <= in;
        default: ;
      endcase
    end
  end

  assign done      = (state == DONE);
  assign out_bytes = data;

endmodule
