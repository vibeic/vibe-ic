module hill_cipher (
    input  logic        clk,
    input  logic        reset,
    input  logic        start,
    input  logic [14:0] plaintext,   // 3 letters, 5 bits each
    input  logic [44:0] key,         // 9 elements, 5 bits each
    output logic [14:0] ciphertext,  // 3 letters, 5 bits each
    output logic        done
);

    logic [4:0] P0, P1, P2;
    logic [4:0] K00, K01, K02;
    logic [4:0] K10, K11, K12;
    logic [4:0] K20, K21, K22;

    // Each product K*P <= 31*31 = 961 (10 bits); the sum of three products is
    // <= 2883 (12 bits). 12-bit accumulators avoid any intermediate truncation.
    logic [11:0] temp0, temp1, temp2;
    // Modulo-26 results are 0..25 (5 bits). The explicit 5-bit cast makes the
    // narrowing intentional (no truncation warning) and leaves no unused bits.
    logic [4:0] c0_mod, c1_mod, c2_mod;

    typedef enum logic [1:0] {
        IDLE        = 2'b00,
        COMPUTE     = 2'b01,
        COMPUTE_MOD = 2'b10,
        DONE        = 2'b11
    } state_t;

    state_t current_state, next_state;

    assign P0 = plaintext[14:10];
    assign P1 = plaintext[9:5];
    assign P2 = plaintext[4:0];

    assign K00 = key[44:40];
    assign K01 = key[39:35];
    assign K02 = key[34:30];
    assign K10 = key[29:25];
    assign K11 = key[24:20];
    assign K12 = key[19:15];
    assign K20 = key[14:10];
    assign K21 = key[9:5];
    assign K22 = key[4:0];

    always_ff @(posedge clk or posedge reset) begin
        if (reset)
            current_state <= IDLE;
        else
            current_state <= next_state;
    end

    always_comb begin
        next_state = current_state;
        done       = 1'b0;
        case (current_state)
            IDLE:        if (start) next_state = COMPUTE;
            COMPUTE:     next_state = COMPUTE_MOD;
            COMPUTE_MOD: next_state = DONE;
            DONE: begin
                done       = 1'b1;
                next_state = IDLE;
            end
            default: next_state = IDLE;
        endcase
    end

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            temp0  <= 12'b0;
            temp1  <= 12'b0;
            temp2  <= 12'b0;
            c0_mod <= 5'b0;
            c1_mod <= 5'b0;
            c2_mod <= 5'b0;
        end
        else begin
            case (current_state)
                COMPUTE: begin
                    temp0 <= (12'(K00) * 12'(P0)) + (12'(K01) * 12'(P1)) + (12'(K02) * 12'(P2));
                    temp1 <= (12'(K10) * 12'(P0)) + (12'(K11) * 12'(P1)) + (12'(K12) * 12'(P2));
                    temp2 <= (12'(K20) * 12'(P0)) + (12'(K21) * 12'(P1)) + (12'(K22) * 12'(P2));
                end
                COMPUTE_MOD: begin
                    c0_mod <= 5'(temp0 % 12'd26);
                    c1_mod <= 5'(temp1 % 12'd26);
                    c2_mod <= 5'(temp2 % 12'd26);
                end
                default: begin
                    temp0  <= 12'b0;
                    temp1  <= 12'b0;
                    temp2  <= 12'b0;
                    c0_mod <= 5'b0;
                    c1_mod <= 5'b0;
                    c2_mod <= 5'b0;
                end
            endcase
        end
    end

    assign ciphertext = { c0_mod, c1_mod, c2_mod };

endmodule
