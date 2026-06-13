module TopModule (
  input clk,
  input reset,
  input data,
  output reg shift_ena,
  output reg counting,
  input done_counting,
  output reg done,
  input ack
);
  localparam S0   = 4'd0;  // looking for 1
  localparam S1   = 4'd1;  // saw 1
  localparam S2   = 4'd2;  // saw 11
  localparam S3   = 4'd3;  // saw 110
  localparam SH0  = 4'd4;  // shift_ena for 4 cycles
  localparam SH1  = 4'd5;
  localparam SH2  = 4'd6;
  localparam SH3  = 4'd7;
  localparam CNT  = 4'd8;  // counting
  localparam DN   = 4'd9;  // done

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      S0:  next = data ? S1 : S0;
      S1:  next = data ? S2 : S0;
      S2:  next = data ? S2 : S3;     // 11 stays on 1, ->110 on 0
      S3:  next = data ? SH0 : S0;    // 1101 detected on 1
      SH0: next = SH1;
      SH1: next = SH2;
      SH2: next = SH3;
      SH3: next = CNT;
      CNT: next = done_counting ? DN : CNT;
      DN:  next = ack ? S0 : DN;
      default: next = S0;
    endcase
  end

  always @(posedge clk) begin
    if (reset) state <= S0;
    else       state <= next;
  end

  always @(*) begin
    shift_ena = (state == SH0) || (state == SH1) ||
                (state == SH2) || (state == SH3);
    counting  = (state == CNT);
    done      = (state == DN);
  end
endmodule
