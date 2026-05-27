module TopModule (
    input  clk,
    input  reset,
    input  in,
    output done
);

    localparam IDLE = 2'd0;
    localparam DATA = 2'd1;
    localparam STOP = 2'd2;
    localparam WAIT = 2'd3;  // wait for stop (line=1) after framing error

    reg [1:0] state, next;
    reg [3:0] cnt, cnt_next;

    always @(*) begin
        next     = state;
        cnt_next = cnt;
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
                // 'in' here is the stop bit
                if (in == 1'b1)
                    next = IDLE;   // valid stop -> done asserted this transition
                else
                    next = WAIT;   // framing error
            end
            WAIT: begin
                if (in == 1'b1)
                    next = IDLE;
            end
            default: next = IDLE;
        endcase
    end

    reg done_r;
    always @(posedge clk) begin
        if (reset) begin
            state  <= IDLE;
            cnt    <= 4'd0;
            done_r <= 1'b0;
        end else begin
            state  <= next;
            cnt    <= cnt_next;
            // done pulse the cycle after a valid stop bit
            done_r <= (state == STOP) && (in == 1'b1);
        end
    end

    assign done = done_r;

endmodule
