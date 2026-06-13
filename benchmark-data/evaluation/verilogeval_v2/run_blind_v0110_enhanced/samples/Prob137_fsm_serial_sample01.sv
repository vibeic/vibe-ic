module TopModule(
    input  clk,
    input  reset,
    input  in,
    output done
);
    localparam IDLE = 3'd0,  // line idle / waiting for start bit (0)
               DATA = 3'd1,  // receiving 8 data bits
               STOP = 3'd2,  // checking stop bit (must be 1)
               DONE = 3'd3,  // byte received correctly
               WAIT = 3'd4;  // bad stop bit: wait for a 1

    reg [2:0] state, next;
    reg [3:0] cnt;       // counts data bits received

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? DATA : IDLE;
            DATA: next = (cnt == 4'd7) ? STOP : DATA;
            STOP: next = (in == 1'b1) ? DONE : WAIT;
            DONE: next = (in == 1'b0) ? DATA : IDLE;
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 4'd0;
        end else begin
            state <= next;
            // count data bits while in DATA
            if (state == DATA)
                cnt <= cnt + 4'd1;
            else
                cnt <= 4'd0;
        end
    end

    assign done = (state == DONE);
endmodule
