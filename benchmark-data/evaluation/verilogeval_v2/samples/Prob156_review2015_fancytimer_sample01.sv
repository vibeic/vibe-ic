module TopModule (
  input  clk,
  input  reset,
  input  data,
  output [3:0] count,
  output counting,
  output done,
  input  ack
);

  // Pattern-detect 1101, shift in 4 delay bits (MSB first), count
  // (delay+1)*1000 cycles, then signal done until ack.
  localparam S=0, S1=1, S11=2, S110=3,
             SH=4,        // shifting in the 4 delay bits
             COUNT=5,     // counting down
             DONE=6;
  reg [2:0] state, next;

  reg [3:0] delay;        // shifted-in delay value
  reg [1:0] shcnt;        // counts the 4 shifted bits (0..3)
  reg [3:0] rem;          // remaining whole delay value (count output)
  reg [9:0] subcnt;       // 0..999 sub-counter for each 1000-cycle interval

  wire shift_last = (shcnt == 2'd3);
  wire sub_last   = (subcnt == 10'd999);
  wire rem_last   = (rem == 4'd0);

  always @(*) begin
    case (state)
      S:     next = data ? S1   : S;
      S1:    next = data ? S11  : S;
      S11:   next = data ? S11  : S110;
      S110:  next = data ? SH   : S;
      SH:    next = shift_last ? COUNT : SH;
      COUNT: next = (sub_last && rem_last) ? DONE : COUNT;
      DONE:  next = ack ? S : DONE;
      default: next = S;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= S;
    end else begin
      state <= next;
    end

    // Datapath
    if (reset) begin
      delay  <= 4'd0;
      shcnt  <= 2'd0;
      rem    <= 4'd0;
      subcnt <= 10'd0;
    end else begin
      case (state)
        S110: begin
          // about to start shifting (only if data=1 -> SH)
          shcnt <= 2'd0;
        end
        SH: begin
          delay <= {delay[2:0], data};   // MSB first
          shcnt <= shcnt + 2'd1;
          if (shift_last) begin
            // loaded full delay this cycle; set up counting
            rem    <= {delay[2:0], data};
            subcnt <= 10'd0;
          end
        end
        COUNT: begin
          if (sub_last) begin
            subcnt <= 10'd0;
            if (!rem_last) rem <= rem - 4'd1;
          end else begin
            subcnt <= subcnt + 10'd1;
          end
        end
        default: ;
      endcase
    end
  end

  assign counting = (state == COUNT);
  assign done     = (state == DONE);
  assign count    = rem;

endmodule
