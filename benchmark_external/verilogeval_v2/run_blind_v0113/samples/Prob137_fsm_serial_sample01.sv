module TopModule (
    input  clk,
    input  reset,
    input  in,
    output done
);
    localparam IDLE = 3'd0;  // waiting for start bit (0)
    localparam BIT  = 3'd1;  // receiving 8 data bits
    localparam STOP = 3'd2;  // checking stop bit
    localparam DONE = 3'd3;  // byte received correctly
    localparam WAIT = 3'd4;  // error: wait for line to return to 1

    reg [2:0] state;
    reg [3:0] cnt;

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 4'd0;
        end else begin
            case (state)
                IDLE: begin
                    if (in == 1'b0) begin
                        state <= BIT;
                        cnt   <= 4'd0;
                    end else
                        state <= IDLE;
                end
                BIT: begin
                    if (cnt == 4'd7)
                        state <= STOP;
                    else
                        cnt <= cnt + 4'd1;
                end
                STOP: begin
                    state <= (in == 1'b1) ? DONE : WAIT;
                end
                DONE: begin
                    if (in == 1'b0) begin
                        state <= BIT;
                        cnt   <= 4'd0;
                    end else
                        state <= IDLE;
                end
                WAIT: begin
                    state <= (in == 1'b1) ? IDLE : WAIT;
                end
                default: state <= IDLE;
            endcase
        end
    end

    // Moore output
    assign done = (state == DONE);
endmodule
