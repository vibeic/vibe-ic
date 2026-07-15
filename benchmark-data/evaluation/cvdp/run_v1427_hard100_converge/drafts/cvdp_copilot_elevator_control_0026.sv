/*
 * Elevator Control System
 *
 * This module implements an FSM-based elevator control system capable of managing multiple floors,
 * handling call requests, and responding to emergency stops and overload conditions. The elevator
 * transitions between six main states: Idle, Moving Up, Moving Down, Emergency Halt, Door Open and
 * Overload Halt. It prioritizes floor requests based on direction, moving to the highest or lowest
 * requested floor depending on the current direction. The current floor is visualized on a
 * multiplexed multi-digit seven-segment display driven through a Binary-to-BCD converter.
 */
module elevator_control_system #(
    parameter N = 8, // Number of floors
    parameter DOOR_OPEN_TIME_MS = 500 // Door open time in milliseconds
) (
    input wire clk,                   // 100MHz clock input
    input wire reset,                 // Active-high reset signal
    input wire [N-1:0] call_requests, // External Floor call requests
    input wire emergency_stop,        // Emergency stop signal
    input wire overload_detected,     // Overload detection signal
    output wire [$clog2(N)-1:0] current_floor, // Current floor of the elevator
    output reg direction,             // Elevator direction: 1 = up, 0 = down
    output reg door_open,             // Door open signal
    output reg [2:0] system_status,   // Elevator system state indicator
    output overload_warning,          // Overload warning signal
    output wire [6:0] seven_seg_out,  // Seven-segment display output for current floor visualization
    output wire [3:0] seven_seg_out_anode, // Anode control signals selecting the active display digit
    output wire [3:0] thousand,       // BCD thousands digit of the displayed floor
    output wire [3:0] hundred,        // BCD hundreds digit of the displayed floor
    output wire [3:0] ten,            // BCD tens digit of the displayed floor
    output wire [3:0] one             // BCD ones digit of the displayed floor
);

// State Encoding
localparam IDLE = 3'b000;          // Elevator is idle
localparam MOVING_UP = 3'b001;     // Elevator moving up
localparam MOVING_DOWN = 3'b010;   // Elevator moving down
localparam EMERGENCY_HALT = 3'b011;// Emergency halt state
localparam DOOR_OPEN = 3'b100;     // Door open state
localparam OVERLOAD_HALT = 3'b101; // New state for overload condition

// Internal Registers

reg [N-1:0] call_requests_internal;   // Internal copy of call requests
reg [2:0] present_state, next_state;  // FSM current and next states
reg [$clog2(N)-1:0] max_request;      // Highest requested floor
reg [$clog2(N)-1:0] min_request;      // Lowest requested floor

// Door open time configuration
`ifdef SIMULATION
    localparam CLK_FREQ_MHZ = 100;  // Clock frequency in MHz
    localparam SIM_DOOR_OPEN_TIME_MS = 0.05; // Shorter door open time for simulation
    localparam DOOR_OPEN_CYCLES = (SIM_DOOR_OPEN_TIME_MS * CLK_FREQ_MHZ * 1000); // Door open cycles for simulation
`else
    // Calculating door open cycles based on time and clock frequency
    localparam CLK_FREQ_MHZ = 100;  // Clock frequency in MHz
    localparam DOOR_OPEN_CYCLES = (DOOR_OPEN_TIME_MS * CLK_FREQ_MHZ * 1000);   // Door open cycles for real implementation
`endif

reg [$clog2(DOOR_OPEN_CYCLES)-1:0] door_open_counter; // Counter for door open duration

reg [$clog2(N)-1:0] current_floor_reg, current_floor_next=0;

assign current_floor = current_floor_reg;

// Update overload warning signal
assign overload_warning = (overload_detected == 1 && present_state == OVERLOAD_HALT);


// FSM state transition
always@(posedge clk or posedge reset) begin
    if(reset)begin
        present_state <= IDLE;
        system_status <= IDLE;
        current_floor_reg <= 0;
        max_request <= 0;
        min_request <= N-1;
    end else begin
        present_state <= next_state;
        system_status <= next_state;
        current_floor_reg <= current_floor_next;

        // Calculate max_request and min_request based on active requests
        max_request = 0;
        min_request = N-1;
        for (integer i = 0; i < N; i = i + 1) begin
            if (call_requests_internal[i]) begin
                if (i > max_request) max_request = i;
                if (i < min_request) min_request = i;
            end
        end
    end
end

always@(*)begin
    next_state = present_state;
    current_floor_next = current_floor_reg;

    case(present_state)
        IDLE:begin
            if(overload_detected) begin
                next_state = OVERLOAD_HALT;
            end else if(emergency_stop) begin
                next_state = EMERGENCY_HALT;
            end else if(call_requests_internal != 0)begin
                if(max_request > current_floor_reg)begin
                    next_state = MOVING_UP;
                end else if(min_request < current_floor_reg) begin
                    next_state = MOVING_DOWN;
                end
            end
        end

        MOVING_UP: begin
            if(emergency_stop)begin
                next_state = EMERGENCY_HALT;
            end else if(call_requests_internal[current_floor_reg+1]) begin
                current_floor_next = current_floor_reg + 1;
                next_state = DOOR_OPEN;
            end else if(current_floor_reg >= max_request) begin
                // If we reach the highest request, go idle
                next_state = IDLE;
            end else begin
                current_floor_next = current_floor_reg + 1;
                next_state = MOVING_UP;
            end
        end

        MOVING_DOWN: begin
            if(emergency_stop)begin
                next_state = EMERGENCY_HALT;
            end else if(call_requests_internal[current_floor_reg-1]) begin
                current_floor_next = current_floor_reg - 1;
                next_state = DOOR_OPEN;
            end else if(current_floor_reg <= min_request) begin
                // If we reach the lowest request, go idle
                next_state = IDLE;
            end else begin
                current_floor_next = current_floor_reg - 1;
                next_state = MOVING_DOWN;
            end
        end

        EMERGENCY_HALT: begin
            if (!emergency_stop) begin
                next_state = IDLE;
                current_floor_next = 0; // Optionally reset to ground floor
            end
        end

        DOOR_OPEN: begin
            if(overload_detected) begin
                next_state = OVERLOAD_HALT;
            end else if (door_open_counter == 0) begin
                next_state = IDLE;
            end else begin
                next_state = DOOR_OPEN;
            end
        end

        OVERLOAD_HALT: begin
            if(!overload_detected) begin
                if(door_open) begin
                    next_state = DOOR_OPEN;
                end else begin
                    next_state = IDLE;
                end
            end
        end
    endcase
end


// Door open control logic
always @(posedge clk or posedge reset) begin
    if (reset) begin
        door_open_counter <= 0;
        door_open <= 0;
    end else begin
        if (present_state == OVERLOAD_HALT) begin
            door_open_counter <= DOOR_OPEN_CYCLES;
            door_open <= 1;
        end else if (present_state == DOOR_OPEN) begin
            if (door_open_counter > 0) begin
                door_open <= 1;
                door_open_counter <= door_open_counter - 1;
            end else begin
                door_open <= 0;
                next_state = IDLE;
            end
        end else begin
            door_open <= 0;
            door_open_counter <= DOOR_OPEN_CYCLES; // Reset door open counter
        end
    end
end

// Call request management
always@(*)begin
    if(reset) begin
        call_requests_internal = 0;
    end else begin
        if(call_requests_internal[current_floor_reg])begin
            call_requests_internal[current_floor_reg] = 0;      // Clear served request
        end
        call_requests_internal = call_requests_internal | call_requests;    // Update requests
    end
end

// Direction control logic
always@(*)begin
    if(reset) begin
        direction = 1;
    end else begin
        if(present_state == MOVING_UP)begin
            direction = 1;
        end else if (present_state == MOVING_DOWN) begin
            direction = 0;
        end else begin
            direction = 1;
        end
    end
end

// ----------------------------------------
// Seven-Segment Display Converter
// ----------------------------------------
// Zero-extend the current floor to the 8-bit display input
wire [7:0] floor_display_ext;
assign floor_display_ext = current_floor_reg;

floor_to_seven_segment floor_display_converter (
    .clk(clk),
    .floor_display(floor_display_ext),
    .seven_seg_out(seven_seg_out),
    .seven_seg_out_anode(seven_seg_out_anode),
    .thousand(thousand),
    .hundred(hundred),
    .ten(ten),
    .one(one)
);

endmodule


/*
 * Floor to Seven-Segment Display Converter
 *
 * Converts the binary floor number to a multi-digit BCD representation (thousand, hundred,
 * ten, one) and dynamically drives a single seven-segment display. A clock-driven refresh
 * counter multiplexes between the four digits; the anode signals select which digit is
 * active (active-low, one digit at a time). Invalid digit values result in a blank display.
 */
module floor_to_seven_segment (
    input wire clk,                        // Clock input driving the digit multiplexing counter
    input wire [7:0] floor_display,        // Binary floor number input
    output reg [6:0] seven_seg_out,        // Seven-segment display output: {a, b, c, d, e, f, g}
    output reg [3:0] seven_seg_out_anode,  // Anode control signals (active-low, one digit active at a time)
    output wire [3:0] thousand,            // BCD thousands digit
    output wire [3:0] hundred,             // BCD hundreds digit
    output wire [3:0] ten,                 // BCD tens digit
    output wire [3:0] one                  // BCD ones digit
);

    // 1. BCD conversion module splitting `floor_display` into `thousand`, `hundred`, `ten`, `one`.
    Binary2BCD bcd_converter (
        .num(floor_display),
        .thousand(thousand),
        .hundred(hundred),
        .ten(ten),
        .one(one)
    );

    // 2. Clock-driven refresh counter to multiplex between the digits for a dynamic display.
    reg [19:0] refresh_counter = 20'd0;

    always @(posedge clk) begin
        refresh_counter <= refresh_counter + 1'b1;
    end

    wire [1:0] digit_select = refresh_counter[19:18];

    // Select the active digit and its anode (active-low)
    reg [3:0] bcd_digit;

    always @(*) begin
        case (digit_select)
            2'b00: begin
                seven_seg_out_anode = 4'b1110; // Ones digit active
                bcd_digit = one;
            end
            2'b01: begin
                seven_seg_out_anode = 4'b1101; // Tens digit active
                bcd_digit = ten;
            end
            2'b10: begin
                seven_seg_out_anode = 4'b1011; // Hundreds digit active
                bcd_digit = hundred;
            end
            2'b11: begin
                seven_seg_out_anode = 4'b0111; // Thousands digit active
                bcd_digit = thousand;
            end
            default: begin
                seven_seg_out_anode = 4'b1111; // All digits off
                bcd_digit = 4'd0;
            end
        endcase
    end

    // Map the selected BCD digit to its seven-segment display encoding
    always @(*) begin
        case (bcd_digit)
            4'd0: seven_seg_out = 7'b1111110; // 0
            4'd1: seven_seg_out = 7'b0110000; // 1
            4'd2: seven_seg_out = 7'b1101101; // 2
            4'd3: seven_seg_out = 7'b1111001; // 3
            4'd4: seven_seg_out = 7'b0110011; // 4
            4'd5: seven_seg_out = 7'b1011011; // 5
            4'd6: seven_seg_out = 7'b1011111; // 6
            4'd7: seven_seg_out = 7'b1110000; // 7
            4'd8: seven_seg_out = 7'b1111111; // 8
            4'd9: seven_seg_out = 7'b1111011; // 9
            default: seven_seg_out = 7'b0000000; // Blank display for invalid digit values
        endcase
    end

endmodule


/*
 * Binary to BCD Converter (Double-Dabble / Shift-and-Add-3 algorithm)
 *
 * Converts an 8-bit binary number into its BCD representation.
 * The thousands place is always 0 since the maximum 8-bit value is 255.
 */
module Binary2BCD(input [7:0] num,output reg [3:0]thousand, output reg [3:0]hundred, output reg [3:0]ten, output reg [3:0]one );
    reg[19:0] shift;
    integer i;

    always @(num)
    begin
        // Initialize the shift register and clear upper bits
        shift = 20'd0;
        // Load the binary input into the lower 8 bits of the shift register
        shift[7:0] = num;

        // Iteratively process the binary number to convert it to BCD
        for(i=0;i<8;i=i+1)
        begin
            // Check and adjust the BCD digits in the shift register if greater than or equal to 5
            if (shift[11:8] >= 4'd5)
                shift[11:8] = shift[11:8] + 4'd3;
            if (shift[15:12] >= 4'd5)
                shift[15:12] = shift[15:12] + 4'd3;
            if (shift[19:16] >= 4'd5)
                shift[19:16] = shift[19:16] + 4'd3;
            // Perform left shift to move to the next bit
            shift = shift << 1;
        end

        // Assign the BCD values from the shift register to the output registers
        one     = shift[11:8];
        ten     = shift[15:12];
        hundred = shift[19:16];
        // Assign the thousands place as 0 (not used in this design)
        thousand = 4'd0;

    end

endmodule
