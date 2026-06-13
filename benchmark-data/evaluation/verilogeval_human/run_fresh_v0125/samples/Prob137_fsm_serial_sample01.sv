module TopModule (
  input clk,
  input in,
  input reset,
  output done
);

  localparam IDLE = 2'd0;  // waiting for start bit (in==0)
  localparam DATA = 2'd1;  // receiving 8 data bits
  localparam STOP = 2'd2;  // checking stop bit
  localparam WAIT = 2'd3;  // bad stop, wait for line idle (in==1)

  reg [1:0] state, next;
  reg [3:0] cnt, cnt_next;
  reg done_reg, done_next;

  always @(*) begin
    next     = state;
    cnt_next = cnt;
    done_next = 1'b0;
    case (state)
      IDLE: begin
        if (in == 1'b0) begin
          next     = DATA;
          cnt_next = 4'd0;
        end
      end
      DATA: begin
        if (cnt == 4'd7) begin
          next = STOP;
        end else begin
          cnt_next = cnt + 4'd1;
        end
      end
      STOP: begin
        if (in == 1'b1) begin
          done_next = 1'b1;   // stop bit correct -> done next cycle
          next      = IDLE;   // return to idle, look for next start bit
        end else begin
          next = WAIT;        // bad stop, resync
        end
      end
      WAIT: begin
        if (in == 1'b1)
          next = IDLE;
      end
      default: next = IDLE;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state    <= IDLE;
      cnt      <= 4'd0;
      done_reg <= 1'b0;
    end else begin
      state    <= next;
      cnt      <= cnt_next;
      done_reg <= done_next;
    end
  end

  assign done = done_reg;

endmodule
