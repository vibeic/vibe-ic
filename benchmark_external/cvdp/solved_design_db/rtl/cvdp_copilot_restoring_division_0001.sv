module restoring_division #(
    parameter WIDTH = 6
)(
    input  wire             clk,        // Clock signal
    input  wire             rst,        // Active-low asynchronous reset
    input  wire             start,      // Active-high start
    input  wire [WIDTH-1:0] dividend,   // Dividend
    input  wire [WIDTH-1:0] divisor,    // Divisor
    output reg  [WIDTH-1:0] quotient,   // Quotient
    output reg  [WIDTH-1:0] remainder,  // Remainder
    output reg              valid       // Active-high one-cycle completion strobe
);

    localparam IDLE = 2'd0,
               BUSY = 2'd1;

    reg [1:0]                 state;
    reg [WIDTH-1:0]           div_reg;    // latched divisor
    reg [WIDTH-1:0]           dvnd_reg;   // remaining dividend bits (MSB shifted out)
    reg [WIDTH:0]             rem_reg;    // WIDTH+1 bit partial remainder
    reg [WIDTH-1:0]           quot_reg;   // quotient under construction
    reg [$clog2(WIDTH+1):0]   cnt;        // iteration counter

    // One restoring-division step (combinational):
    //   shift the remainder left, bring in the next dividend MSB, then try
    //   to subtract the divisor.  A non-negative result means the divisor
    //   fits -> quotient bit 1 and keep the difference; otherwise restore.
    wire [WIDTH:0] rem_shifted = {rem_reg[WIDTH-1:0], dvnd_reg[WIDTH-1]};
    wire [WIDTH:0] sub_res     = rem_shifted - {1'b0, div_reg};
    wire           fits        = ~sub_res[WIDTH];
    wire [WIDTH:0] rem_next    = fits ? sub_res : rem_shifted;
    wire [WIDTH-1:0] quot_next = {quot_reg[WIDTH-2:0], fits};

    always @(posedge clk or negedge rst) begin
        if (!rst) begin
            state     <= IDLE;
            quotient  <= {WIDTH{1'b0}};
            remainder <= {WIDTH{1'b0}};
            valid     <= 1'b0;
            div_reg   <= {WIDTH{1'b0}};
            dvnd_reg  <= {WIDTH{1'b0}};
            rem_reg   <= {(WIDTH+1){1'b0}};
            quot_reg  <= {WIDTH{1'b0}};
            cnt       <= {($clog2(WIDTH+1)+1){1'b0}};
        end else begin
            case (state)
                IDLE: begin
                    valid <= 1'b0;
                    if (start) begin
                        div_reg  <= divisor;
                        dvnd_reg <= dividend;
                        rem_reg  <= {(WIDTH+1){1'b0}};
                        quot_reg <= {WIDTH{1'b0}};
                        cnt      <= {($clog2(WIDTH+1)+1){1'b0}};
                        state    <= BUSY;
                    end
                end
                BUSY: begin
                    rem_reg  <= rem_next;
                    quot_reg <= quot_next;
                    dvnd_reg <= {dvnd_reg[WIDTH-2:0], 1'b0};
                    cnt      <= cnt + 1'b1;
                    if (cnt == (WIDTH-1)) begin
                        // final iteration : present the result and pulse valid
                        quotient  <= quot_next;
                        remainder <= rem_next[WIDTH-1:0];
                        valid     <= 1'b1;
                        state     <= IDLE;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end

endmodule
