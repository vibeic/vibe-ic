module TopModule (
  input wire clk,
  input wire reset,
  input wire data,
  output wire [3:0] count,
  output reg counting,
  output reg done,
  input wire ack
);

  localparam S    = 4'd0,  // searching for 1101
             S1   = 4'd1,
             S11  = 4'd2,
             S110 = 4'd3,
             SH0  = 4'd4,  // shift in delay bit (MSB first)
             SH1  = 4'd5,
             SH2  = 4'd6,
             SH3  = 4'd7,
             CNT  = 4'd8,  // counting
             DN   = 4'd9;  // done, wait for ack
  reg [3:0] state, next;

  reg [3:0]  delay;        // remaining seconds (count value)
  reg [9:0]  subcnt;       // counts 0..999 within each unit
  reg [3:0]  shiftreg;     // collects the 4 delay bits

  // Pattern + shift sequencing
  always @(*) begin
    case (state)
      S:    next = data ? S1   : S;
      S1:   next = data ? S11  : S;
      S11:  next = data ? S11  : S110;
      S110: next = data ? SH0  : S;        // 1101 detected
      SH0:  next = SH1;
      SH1:  next = SH2;
      SH2:  next = SH3;
      SH3:  next = CNT;
      CNT:  next = (delay == 4'd0 && subcnt == 10'd999) ? DN : CNT;
      DN:   next = ack ? S : DN;
      default: next = S;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state    <= S;
      delay    <= 4'd0;
      subcnt   <= 10'd0;
      shiftreg <= 4'd0;
    end else begin
      state <= next;

      // shift in 4 delay bits, MSB first
      case (state)
        SH0, SH1, SH2: shiftreg <= {shiftreg[2:0], data};
        SH3: begin
          delay  <= {shiftreg[2:0], data};   // final 4-bit delay
          subcnt <= 10'd0;
        end
        CNT: begin
          if (subcnt == 10'd999) begin
            subcnt <= 10'd0;
            if (delay != 4'd0)
              delay <= delay - 4'd1;
          end else begin
            subcnt <= subcnt + 10'd1;
          end
        end
        default: ;
      endcase
    end
  end

  always @(*) begin
    counting = (state == CNT);
    done     = (state == DN);
  end

  assign count = delay;

endmodule
