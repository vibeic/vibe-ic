module TopModule (
    input  clk,
    input  reset,
    input  in,
    output done
);

    localparam IDLE  = 3'd0;  // line idle / waiting for start bit
    localparam DATA  = 3'd1;  // receiving 8 data bits
    localparam STOP  = 3'd2;  // checking stop bit
    localparam DONE  = 3'd3;  // byte received correctly
    localparam WAIT  = 3'd4;  // error: wait for stop bit (in==1)

    reg [2:0] state, next;
    reg [3:0] cnt;            // counts data bits received

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? DATA : IDLE;       // start bit
            DATA: next = (cnt == 4'd7) ? STOP : DATA;      // 8 data bits
            STOP: next = (in == 1'b1) ? DONE : WAIT;       // verify stop bit
            DONE: next = (in == 1'b0) ? DATA : IDLE;       // back-to-back start?
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;       // wait for stop bit
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 4'd0;
        end else begin
            state <= next;
            if (state == DATA)
                cnt <= cnt + 4'd1;
            else
                cnt <= 4'd0;
        end
    end

    assign done = (state == DONE);

endmodule
