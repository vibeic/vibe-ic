module TopModule (
  input clk,
  input [7:0] in,
  input reset,
  output done
);

  localparam BYTE1 = 2'd0;
  localparam BYTE2 = 2'd1;
  localparam BYTE3 = 2'd2;
  localparam DONE  = 2'd3;

  reg [1:0] state;

  always @(posedge clk) begin
    if (reset)
      state <= BYTE1;
    else begin
      case (state)
        BYTE1: state <= in[3] ? BYTE2 : BYTE1;
        BYTE2: state <= BYTE3;
        BYTE3: state <= DONE;
        DONE:  state <= in[3] ? BYTE2 : BYTE1;
        default: state <= BYTE1;
      endcase
    end
  end

  assign done = (state == DONE);

endmodule
