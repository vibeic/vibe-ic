module TopModule (
    input            clk,
    input            in,
    input            reset,
    output reg [7:0] out_byte,
    output reg       done
);

    localparam IDLE  = 4'd0;   // waiting for start bit (line idle = 1)
    localparam D0    = 4'd1;   // receiving data bit 0
    localparam D1    = 4'd2;
    localparam D2    = 4'd3;
    localparam D3    = 4'd4;
    localparam D4    = 4'd5;
    localparam D5    = 4'd6;
    localparam D6    = 4'd7;
    localparam D7    = 4'd8;
    localparam STOP  = 4'd9;   // expect stop bit (1)
    localparam DONE  = 4'd10;  // good stop seen, assert done
    localparam WAIT  = 4'd11;  // bad stop, wait until line returns to 1

    reg [3:0] state, next;
    reg [7:0] shift;

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? D0 : IDLE;  // start bit
            D0:   next = D1;
            D1:   next = D2;
            D2:   next = D3;
            D3:   next = D4;
            D4:   next = D5;
            D5:   next = D6;
            D6:   next = D7;
            D7:   next = STOP;
            STOP: next = (in == 1'b1) ? DONE : WAIT;
            DONE: next = (in == 1'b0) ? D0 : IDLE;  // ready for next byte
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
        end else begin
            state <= next;
        end
    end

    // shift in data bits LSB first
    always @(posedge clk) begin
        case (state)
            D0: shift[0] <= in;
            D1: shift[1] <= in;
            D2: shift[2] <= in;
            D3: shift[3] <= in;
            D4: shift[4] <= in;
            D5: shift[5] <= in;
            D6: shift[6] <= in;
            D7: shift[7] <= in;
            default: ;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            done     <= 1'b0;
            out_byte <= 8'b0;
        end else begin
            if (next == DONE) begin
                done     <= 1'b1;
                out_byte <= shift;
            end else begin
                done     <= 1'b0;
            end
        end
    end

endmodule
