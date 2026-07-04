module divider #
(
    parameter WIDTH = 32
)
(
    input  wire                  clk,
    input  wire                  rst_n,      // Active-low asynchronous reset
    input  wire                  start,      // Start signal for new operation
    input  wire [WIDTH-1 : 0]    dividend,   // Dividend (numerator)
    input  wire [WIDTH-1 : 0]    divisor,    // Divisor (denominator)
    output wire [WIDTH-1 : 0]    quotient,   // Result of the division
    output wire [WIDTH-1 : 0]    remainder,  // Remainder after division
    output wire                  valid       // Indicates output is valid
);

    localparam AW = WIDTH + 1;
    // Simple 3-state FSM
    localparam IDLE = 2'b00;
    localparam BUSY = 2'b01;
    localparam DONE = 2'b10;

    reg [1:0] state_reg, state_next;

    // A+Q combined into one WIDTH + 1 + WIDTH register:
    reg [AW+WIDTH-1 : 0] aq_reg,   aq_next;

    // Divisor register
    reg [AW-1 : 0]       m_reg,    m_next;

    // Iterate exactly WIDTH times
    reg [$clog2(WIDTH)-1:0] n_reg, n_next;

    // Final outputs
    reg [WIDTH-1:0] quotient_reg, quotient_next;
    reg [WIDTH-1:0] remainder_reg, remainder_next;
    reg valid_reg, valid_next;

    // Assign the top-level outputs
    assign quotient  = quotient_reg;
    assign remainder = remainder_reg;
    assign valid     = valid_reg;

    // ---- combinational next-state / datapath ----
    reg [AW+WIDTH-1:0] aq_shift;
    reg [AW-1:0]       a_s, a_new, a_final;
    reg [WIDTH-1:0]    q_s;

    always @(*) begin
        state_next     = state_reg;
        aq_next        = aq_reg;
        m_next         = m_reg;
        n_next         = n_reg;
        quotient_next  = quotient_reg;
        remainder_next = remainder_reg;
        valid_next     = valid_reg;

        // defaults for datapath temporaries
        aq_shift = aq_reg << 1;
        a_s      = aq_shift[AW+WIDTH-1 : WIDTH];
        q_s      = aq_shift[WIDTH-1 : 0];
        // add when current A is negative, subtract otherwise
        a_new    = aq_reg[AW+WIDTH-1] ? (a_s + m_reg) : (a_s - m_reg);
        a_final  = a_new;   // default; final Step-8 adjust applied below

        case (state_reg)
            IDLE: begin
                valid_next = 1'b0;
                if (start) begin
                    aq_next    = { {AW{1'b0}}, dividend };  // A=0, Q=dividend
                    m_next     = { 1'b0, divisor };         // zero-extended divisor
                    n_next     = {($clog2(WIDTH)){1'b0}};
                    state_next = BUSY;
                end
            end

            BUSY: begin
                // one non-restoring step:
                //   shift AQ left, then add/sub M, then Q[0] = ~sign(A)
                aq_next = { a_new, q_s[WIDTH-1:1], ~a_new[AW-1] };

                if (n_reg == (WIDTH-1)) begin
                    // last iteration done -> compute final outputs (Step-8 adjust)
                    // and move to DONE. 'valid' is asserted in the dedicated
                    // DONE cycle (Total Latency = WIDTH + 2: 1 load + WIDTH busy
                    // + 1 DONE), so it is NOT raised here.
                    a_final        = a_new[AW-1] ? (a_new + m_reg) : a_new;
                    quotient_next  = { q_s[WIDTH-1:1], ~a_new[AW-1] };
                    remainder_next = a_final[WIDTH-1:0];
                    state_next     = DONE;
                end else begin
                    n_next = n_reg + 1'b1;
                end
            end

            DONE: begin
                // Dedicated DONE cycle: assert valid here (one cycle after the
                // final BUSY iteration) and hold until start is de-asserted.
                valid_next = 1'b1;
                if (!start)
                    state_next = IDLE;
            end

            default: state_next = IDLE;
        endcase
    end

    // ---- sequential ----
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_reg     <= IDLE;
            aq_reg        <= {(AW+WIDTH){1'b0}};
            m_reg         <= {AW{1'b0}};
            n_reg         <= {($clog2(WIDTH)){1'b0}};
            quotient_reg  <= {WIDTH{1'b0}};
            remainder_reg <= {WIDTH{1'b0}};
            valid_reg     <= 1'b0;
        end else begin
            state_reg     <= state_next;
            aq_reg        <= aq_next;
            m_reg         <= m_next;
            n_reg         <= n_next;
            quotient_reg  <= quotient_next;
            remainder_reg <= remainder_next;
            valid_reg     <= valid_next;
        end
    end

endmodule
