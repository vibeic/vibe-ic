module TopModule (
    input  clk,
    input  reset,
    input  in,
    output done
);

    localparam IDLE = 3'd0;  // line idle/high, wait for start bit (0)
    localparam DATA = 3'd1;  // receiving 8 data bits
    localparam STOP = 3'd2;  // check stop bit
    localparam DONE = 3'd3;  // byte received correctly -> done
    localparam WAIT = 3'd4;  // bad stop bit, wait for a 1 (stop) before next byte

    reg [2:0] state, next;
    reg [3:0] cnt, cnt_next;

    always @(*) begin
        next = state;
        cnt_next = cnt;
        case (state)
            IDLE: begin
                if (in == 1'b0) begin   // start bit
                    next = DATA;
                    cnt_next = 4'd0;
                end
            end
            DATA: begin
                if (cnt == 4'd7) begin  // 8th data bit consumed this cycle
                    next = STOP;
                end else begin
                    cnt_next = cnt + 4'd1;
                end
            end
            STOP: begin
                if (in == 1'b1)         // valid stop bit
                    next = DONE;
                else
                    next = WAIT;        // bad stop -> wait for a stop bit
            end
            DONE: begin
                if (in == 1'b0) begin   // immediate next start bit
                    next = DATA;
                    cnt_next = 4'd0;
                end else
                    next = IDLE;
            end
            WAIT: begin
                if (in == 1'b1)
                    next = IDLE;        // found a stop bit, ready again
            end
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 4'd0;
        end else begin
            state <= next;
            cnt   <= cnt_next;
        end
    end

    assign done = (state == DONE);

endmodule
