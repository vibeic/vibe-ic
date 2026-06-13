module TopModule (
    input        clk,
    input        in,
    input        reset,
    output [7:0] out_byte,
    output       done
);
    localparam IDLE  = 3'd0;  // waiting for start bit (line=1 idle)
    localparam DATA  = 3'd1;  // shifting in 8 data bits
    localparam STOP  = 3'd2;  // expecting stop bit (1)
    localparam DONE  = 3'd3;  // stop bit good -> done
    localparam WAIT  = 3'd4;  // stop bit bad -> wait for a 1 (stop) before resync

    reg [2:0] state, next;
    reg [3:0] cnt;
    reg [7:0] shifter;

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? DATA : IDLE;       // start bit detected
            DATA: next = (cnt == 4'd7) ? STOP : DATA;       // after 8 bits
            STOP: next = (in == 1'b1) ? DONE : WAIT;        // stop bit check
            DONE: next = (in == 1'b0) ? DATA : IDLE;        // can start next immediately
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;        // resync: wait for idle/stop
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state   <= IDLE;
            cnt     <= 4'd0;
            shifter <= 8'd0;
        end else begin
            state <= next;
            if (state == DATA) begin
                shifter <= {in, shifter[7:1]};  // LSB first
                cnt     <= cnt + 4'd1;
            end else begin
                cnt <= 4'd0;
            end
        end
    end

    assign done     = (state == DONE);
    assign out_byte = shifter;
endmodule
