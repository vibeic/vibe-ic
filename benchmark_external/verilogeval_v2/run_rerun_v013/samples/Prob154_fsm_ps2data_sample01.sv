module TopModule (
  input         clk,
  input         reset,
  input  [7:0]  in,
  output [23:0] out_bytes,
  output        done
);

  localparam BYTE1 = 2'd0;  // searching for in[3]=1 (first byte)
  localparam BYTE2 = 2'd1;
  localparam BYTE3 = 2'd2;
  localparam DONE  = 2'd3;

  reg [1:0] state, next;
  reg [7:0] b1, b2, b3;

  always @(*) begin
    case (state)
      BYTE1: next = in[3] ? BYTE2 : BYTE1;
      BYTE2: next = BYTE3;
      BYTE3: next = DONE;
      DONE:  next = in[3] ? BYTE2 : BYTE1;  // DONE also looks for the next message's first byte
      default: next = BYTE1;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= BYTE1;
      b1 <= 8'd0;
      b2 <= 8'd0;
      b3 <= 8'd0;
    end else begin
      state <= next;
      case (state)
        BYTE1: if (in[3]) b1 <= in;
        BYTE2: b2 <= in;
        BYTE3: b3 <= in;
        DONE:  if (in[3]) b1 <= in;
        default: ;
      endcase
    end
  end

  assign done      = (state == DONE);
  assign out_bytes = {b1, b2, b3};

endmodule
