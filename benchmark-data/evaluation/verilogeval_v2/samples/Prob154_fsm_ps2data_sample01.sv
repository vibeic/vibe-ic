module TopModule (
  input  clk,
  input  reset,
  input  [7:0] in,
  output [23:0] out_bytes,
  output done
);

  localparam BYTE1=0, BYTE2=1, BYTE3=2, DONE=3;
  reg [1:0] state, next;
  reg [7:0] b1, b2;
  reg [23:0] out_reg;

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
    if (reset) begin
      state <= BYTE1;
    end else begin
      state <= next;
      case (state)
        BYTE1: if (in[3]) b1 <= in;
        BYTE2: b2 <= in;
        BYTE3: out_reg <= {b1, b2, in};
        DONE:  if (in[3]) b1 <= in;
        default: ;
      endcase
    end
  end

  assign done      = (state == DONE);
  assign out_bytes = out_reg;

endmodule
