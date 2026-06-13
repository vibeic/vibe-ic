module TopModule (
    input        clk,
    input        in,
    input        reset,
    output [7:0] out_byte,
    output       done
);
    localparam IDLE = 2'd0;   // waiting for start bit (in==0)
    localparam DATA = 2'd1;   // shifting in 8 data bits
    localparam STOP = 2'd2;   // checking stop bit -> done if in==1
    localparam WAIT = 2'd3;   // bad stop bit: wait until line returns to 1

    reg [1:0] state, next;
    reg [3:0] cnt;            // counts data bits received
    reg [7:0] shifter;        // collected byte (LSB first)
    reg [7:0] hold;           // latched output byte
    reg       done_r;

    always @(*) begin
        case (state)
            IDLE: next = (in == 1'b0) ? DATA : IDLE;
            DATA: next = (cnt == 4'd7) ? STOP : DATA;
            STOP: next = (in == 1'b1) ? IDLE : WAIT;  // good stop bit -> idle, else wait for line=1
            WAIT: next = (in == 1'b1) ? IDLE : WAIT;
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state   <= IDLE;
            cnt     <= 4'd0;
            shifter <= 8'd0;
            hold    <= 8'd0;
            done_r  <= 1'b0;
        end else begin
            state <= next;
            done_r <= 1'b0;

            case (state)
                IDLE: cnt <= 4'd0;
                DATA: begin
                    shifter <= {in, shifter[7:1]};   // LSB first -> shift right
                    cnt <= cnt + 4'd1;
                end
                STOP: begin
                    if (in == 1'b1) begin            // valid stop bit
                        hold   <= shifter;
                        done_r <= 1'b1;
                    end
                end
                default: ;
            endcase
        end
    end

    assign out_byte = hold;
    assign done     = done_r;
endmodule
