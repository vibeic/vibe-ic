module TopModule (
    input            clk,
    input            in,
    input            reset,
    output reg [7:0] out_byte,
    output           done
);
    localparam IDLE  = 2'd0;  // waiting for start bit (0)
    localparam DATA  = 2'd1;  // shifting in 8 data bits
    localparam STOP  = 2'd2;  // checking stop bit
    localparam WAITE = 2'd3;  // error: wait for a stop bit (a 1) before resuming

    reg [1:0] state, next;
    reg [3:0] cnt;       // counts data bits received
    reg [7:0] shifter;

    always @(*) begin
        case (state)
            IDLE:  next = (in == 1'b0) ? DATA : IDLE;        // start bit detected
            DATA:  next = (cnt == 4'd7) ? STOP : DATA;       // after 8 bits, check stop
            STOP:  next = (in == 1'b1) ? IDLE : WAITE;       // good stop -> done; else wait
            WAITE: next = (in == 1'b1) ? IDLE : WAITE;       // wait until line returns to 1
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
                shifter <= {in, shifter[7:1]};  // LSB first
                cnt <= cnt + 4'd1;
            end else begin
                cnt <= 4'd0;
            end
        end
    end

    // done asserted in the cycle a valid stop bit is found (state==STOP, in==1)
    assign done = (state == STOP) && (in == 1'b1);

    always @(*) out_byte = shifter;
endmodule
