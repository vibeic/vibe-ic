module TopModule (
    input  clk,
    input  reset,
    input  in,
    output done
);
    localparam IDLE = 3'd0;  // wait for start bit (in==0)
    localparam DATA = 3'd1;  // receiving 8 data bits
    localparam STOP = 3'd2;  // check stop bit
    localparam DONE = 3'd3;  // byte received OK
    localparam WAIT = 3'd4;  // bad stop: wait for line to return to 1

    reg [2:0] state;
    reg [2:0] cnt;

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 3'd0;
        end else begin
            case (state)
                IDLE: begin
                    if (in == 1'b0) begin   // start bit
                        state <= DATA;
                        cnt   <= 3'd0;
                    end else
                        state <= IDLE;
                end
                DATA: begin
                    if (cnt == 3'd7) begin
                        state <= STOP;
                    end else begin
                        cnt   <= cnt + 3'd1;
                    end
                end
                STOP: begin
                    if (in == 1'b1)
                        state <= DONE;      // valid stop bit
                    else
                        state <= WAIT;      // bad stop bit
                end
                DONE: begin
                    if (in == 1'b0) begin   // immediate next start bit
                        state <= DATA;
                        cnt   <= 3'd0;
                    end else
                        state <= IDLE;
                end
                WAIT: begin
                    if (in == 1'b1)
                        state <= IDLE;
                    else
                        state <= WAIT;
                end
                default: state <= IDLE;
            endcase
        end
    end

    assign done = (state == DONE);
endmodule
