module TopModule (
    input        clk,
    input        in,
    input        reset,
    output [7:0] out_byte,
    output       done
);
    localparam IDLE = 3'd0, DATA = 3'd1, STOP = 3'd2, DONE = 3'd3, WAIT = 3'd4;
    reg [2:0] state, next;
    reg [3:0] cnt;
    reg [7:0] shifter;

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? DATA : IDLE;     // saw start bit
            DATA: next = (cnt == 4'd7) ? STOP : DATA;     // 8 data bits
            STOP: next = (in == 1'b1) ? DONE : WAIT;      // stop bit must be 1
            DONE: next = (in == 1'b0) ? DATA : IDLE;      // can start next immediately
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;      // wait for a stop (idle) bit
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 4'd0;
        end else begin
            state <= next;
            if (state == DATA) begin
                shifter <= {in, shifter[7:1]}; // LSB first
                cnt <= cnt + 4'd1;
            end else begin
                cnt <= 4'd0;
            end
        end
    end

    assign done = (state == DONE);
    assign out_byte = shifter;
endmodule
