// ---------------------------------------------------------------------------
// Digital Dice Roller
// ---------------------------------------------------------------------------
// Controls rolling of a 6-sided die.
//  - FSM with two states: IDLE and ROLLING.
//  - While `button` is HIGH the internal 3-bit register `counter` cycles
//    through the dice values 1..6 (one step per positive clock edge,
//    wrapping 6 -> 1).
//  - When `button` returns LOW the FSM goes back to IDLE and `dice_value`
//    presents the last counter value reached while rolling (always 1..6).
//  - Asynchronous active-LOW reset `reset_n` keeps `dice_value` at 000.
// ---------------------------------------------------------------------------
module digital_dice_roller (
    input  wire       clk,        // system clock
    input  wire       reset_n,    // asynchronous active-low reset
    input  wire       button,     // roll while HIGH, show result when LOW
    output reg  [2:0] dice_value  // dice result, valid values 1..6
);

    // FSM state encoding
    localparam IDLE    = 1'b0;
    localparam ROLLING = 1'b1;

    reg       state;
    reg [2:0] counter;  // internal 3-bit counter cycling through 1..6

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state      <= IDLE;
            counter    <= 3'd0;
            dice_value <= 3'd0;
        end else begin
            case (state)
                IDLE: begin
                    // dice_value remains constant in IDLE.
                    if (button) begin
                        // First rolling step counts 1.
                        state   <= ROLLING;
                        counter <= 3'd1;
                    end
                end
                ROLLING: begin
                    if (button) begin
                        // Cycle 1..6, wrapping 6 -> 1.
                        counter <= (counter == 3'd6) ? 3'd1 : counter + 3'd1;
                    end else begin
                        // Button released: present the last rolled value
                        // (always within 1..6) and return to IDLE.
                        state      <= IDLE;
                        dice_value <= counter;
                        counter    <= 3'd0;
                    end
                end
                default: begin
                    state <= IDLE;
                end
            endcase
        end
    end

endmodule
