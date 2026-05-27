module TopModule (
    input         clk,
    input         reset,
    input  [7:0]  in,
    output [23:0] out_bytes,
    output        done
);
    localparam B1   = 2'd0;  // search for byte with in[3]=1
    localparam B2   = 2'd1;  // collecting byte 2
    localparam B3   = 2'd2;  // collecting byte 3
    localparam DONE = 2'd3;  // assert done

    reg [1:0]  state, next;
    reg [23:0] msg;          // shift register for the 3 bytes

    always @(*) begin
        case (state)
            B1:   next = in[3] ? B2 : B1;  // first byte has in[3]=1
            B2:   next = B3;
            B3:   next = DONE;
            DONE: next = in[3] ? B2 : B1;  // immediately scan for the next message
            default: next = B1;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= B1;
            msg   <= 24'd0;
        end else begin
            state <= next;
            // shift the incoming byte into the low end; after 3 captures the
            // message occupies [23:0] with byte1 highest.
            if (state == B1) begin
                if (in[3]) msg <= {16'd0, in};       // start fresh with byte1
            end else if (state == B2 || state == B3) begin
                msg <= {msg[15:0], in};              // append byte2 then byte3
            end else if (state == DONE) begin
                if (in[3]) msg <= {16'd0, in};       // begin next message
            end
        end
    end

    assign done      = (state == DONE);
    assign out_bytes = msg;
endmodule
