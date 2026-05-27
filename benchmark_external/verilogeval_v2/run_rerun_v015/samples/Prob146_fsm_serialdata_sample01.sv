module TopModule(
    input        clk,
    input        in,
    input        reset,
    output [7:0] out_byte,
    output       done
);
    localparam IDLE  = 2'd0; // wait for start bit (in==0)
    localparam DATA  = 2'd1; // shifting in 8 data bits
    localparam STOP  = 2'd2; // check stop bit
    localparam WAIT  = 2'd3; // error: wait for a stop bit (in==1)

    reg [1:0] state, next;
    reg [3:0] cnt;        // counts data bits received
    reg [7:0] shifter;

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? DATA : IDLE;
            DATA: next = (cnt == 4'd7) ? STOP : DATA;
            STOP: next = (in == 1'b1) ? IDLE : WAIT; // valid stop -> done; else wait
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
            if (state == DATA) begin
                cnt     <= cnt + 4'd1;
                shifter <= {in, shifter[7:1]}; // LSB first
            end else begin
                cnt <= 4'd0;
            end
        end
    end

    // done asserted the cycle a valid stop bit is found:
    // in STOP state with in==1
    assign done     = (state == STOP) && (in == 1'b1);
    assign out_byte = shifter;
endmodule
