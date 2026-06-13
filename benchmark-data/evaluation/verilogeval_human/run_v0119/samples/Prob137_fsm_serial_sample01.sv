module TopModule (
  input clk,
  input in,
  input reset,
  output done
);
    localparam IDLE = 3'd0,
               DATA = 3'd1,
               STOP = 3'd2,
               DONE = 3'd3,
               WAIT = 3'd4;

    reg [2:0] state;
    reg [2:0] cnt;   // counts the 8 data bits (0..7)

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 3'd0;
        end else begin
            case (state)
                IDLE: begin
                    cnt <= 3'd0;
                    if (in == 1'b0)      // start bit
                        state <= DATA;
                    else
                        state <= IDLE;
                end
                DATA: begin
                    if (cnt == 3'd7) begin
                        state <= STOP;   // 8 data bits received
                        cnt   <= 3'd0;
                    end else begin
                        cnt   <= cnt + 3'd1;
                        state <= DATA;
                    end
                end
                STOP: begin
                    if (in == 1'b1)
                        state <= DONE;   // valid stop bit
                    else
                        state <= WAIT;   // bad stop -> wait for a 1
                end
                DONE: begin
                    cnt <= 3'd0;
                    if (in == 1'b0)      // immediate new start bit
                        state <= DATA;
                    else
                        state <= IDLE;
                end
                WAIT: begin
                    if (in == 1'b1)
                        state <= IDLE;   // found stop/idle, ready for next
                    else
                        state <= WAIT;
                end
                default: state <= IDLE;
            endcase
        end
    end

    // Moore output
    assign done = (state == DONE);
endmodule
