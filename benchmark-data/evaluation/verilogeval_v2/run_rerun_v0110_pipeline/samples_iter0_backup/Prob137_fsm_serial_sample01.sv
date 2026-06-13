module TopModule (
    input  clk,
    input  reset,
    input  in,
    output done
);
    localparam IDLE = 3'd0, DATA = 3'd1, STOP = 3'd2, DONE = 3'd3, WAIT = 3'd4;
    reg [2:0] state;
    reg [3:0] cnt;

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 4'd0;
        end else begin
            case (state)
                IDLE: begin
                    if (in == 1'b0) begin   // start bit
                        state <= DATA;
                        cnt   <= 4'd0;
                    end
                end
                DATA: begin
                    if (cnt == 4'd7) begin
                        state <= STOP;
                        cnt   <= 4'd0;
                    end else
                        cnt <= cnt + 4'd1;
                end
                STOP: begin
                    if (in == 1'b1)         // valid stop bit
                        state <= DONE;
                    else
                        state <= WAIT;      // wait for a stop bit
                end
                DONE: begin
                    // done asserted this cycle; this cycle's in can start a new byte
                    if (in == 1'b0) begin
                        state <= DATA;
                        cnt   <= 4'd0;
                    end else
                        state <= IDLE;
                end
                WAIT: begin
                    if (in == 1'b1)
                        state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end

    assign done = (state == DONE);
endmodule
