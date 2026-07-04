module coffee_machine #(
    parameter NBW_DLY    = 'd5,
    parameter NBW_BEANS  = 'd2,
    parameter NS_BEANS   = 'd4,
    parameter NS_OP      = 'd3, // Fixed
    parameter NS_SENSOR  = 'd4  // Fixed
) (
    input  logic                 clk,
    input  logic                 rst_async_n,
    input  logic [NBW_DLY-1:0]   i_grind_delay,
    input  logic [NBW_DLY-1:0]   i_heat_delay,
    input  logic [NBW_DLY-1:0]   i_pour_delay,
    input  logic [NBW_BEANS-1:0] i_bean_sel,
    input  logic [NS_OP-1:0]     i_operation_sel,
    input  logic                 i_start,
    input  logic [NS_SENSOR-1:0] i_sensor,
    output logic [NS_BEANS-1:0]  o_bean_sel,
    output logic                 o_grind_beans,
    output logic                 o_use_powder,
    output logic                 o_heat_water,
    output logic                 o_pour_coffee,
    output logic                 o_error
);

    // Fixed delays (reference model: BEAN_SEL_DELAY=3, POWDER_DELAY=2)
    localparam SEL_CYCLES    = 'd3;
    localparam POWDER_CYCLES = 'd2;

    typedef enum logic [2:0] {
        IDLE     = 3'b000,
        BEAN_SEL = 3'b001,
        GRIND    = 3'b011,
        POWDER   = 3'b111,
        HEAT     = 3'b110,
        POUR     = 3'b100
    } state_t;

    state_t               state_ff, state_nx;
    logic [NBW_DLY:0]     counter_ff, counter_nx;
    logic [NBW_DLY-1:0]   grind_delay_ff, heat_delay_ff, pour_delay_ff;
    logic [NS_OP-1:0]     operation_sel_ff;
    logic [NBW_BEANS-1:0] bean_sel_in_ff;
    logic                 start_q1;

    // Continuous-assign sensor bit extraction (kept outside always_* to
    // avoid iverilog's "constant select in always" limitation).
    logic sensor_nowater, sensor_nobeans, sensor_nopowder, sensor_generic;
    assign sensor_nowater  = i_sensor[0];
    assign sensor_nobeans  = i_sensor[1];
    assign sensor_nopowder = i_sensor[2];
    assign sensor_generic  = i_sensor[3];

    // ----------------------------------------------------------------
    // IDLE-state error condition (matches reference update_error()).
    // Generic error (i_sensor[3]) applies in every state; the rest only
    // when IDLE. The machine cannot start while this condition holds.
    // ----------------------------------------------------------------
    logic error_idle;
    always_comb begin : error_idle_logic
        error_idle = sensor_generic
                   | sensor_nowater
                   | (sensor_nobeans  & ((i_operation_sel == 3'b010) | (i_operation_sel == 3'b011)))
                   | (sensor_nopowder & ((i_operation_sel == 3'b100) | (i_operation_sel == 3'b001)))
                   | (i_operation_sel == 3'b110) | (i_operation_sel == 3'b111);
    end

    // Qualified start: asserted only from IDLE and only when no idle error.
    logic start_ok;
    assign start_ok = i_start & (state_ff == IDLE) & ~error_idle;

    // ----------------------------------------------------------------
    // Error output (combinational, Moore on state).
    // ----------------------------------------------------------------
    always_comb begin : error_logic
        if (sensor_generic) begin
            o_error = 1'b1;            // generic error, any state
        end else if (state_ff == IDLE) begin
            o_error = error_idle;      // i_sensor[3] already handled above
        end else begin
            o_error = 1'b0;
        end
    end

    // ----------------------------------------------------------------
    // Sequential: start pipeline (2-cycle launch latency), operation
    // latching, delay counter, FSM state register.
    // ----------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_async_n) begin : seq_regs
        if (~rst_async_n) begin
            state_ff   <= IDLE;
            start_q1   <= 1'b0;
            counter_ff <= '0;
        end else begin
            state_ff   <= state_nx;
            start_q1   <= start_ok;
            counter_ff <= counter_nx;
        end
    end

    always_ff @(posedge clk) begin : latch_regs
        if (start_ok) begin
            operation_sel_ff <= i_operation_sel;
            grind_delay_ff   <= i_grind_delay;
            heat_delay_ff    <= i_heat_delay;
            pour_delay_ff    <= i_pour_delay;
            bean_sel_in_ff   <= i_bean_sel;
        end
    end

    // ----------------------------------------------------------------
    // FSM next-state / counter. A generic error (i_sensor[3]) while the
    // FSM is running aborts the operation and forces IDLE on the next
    // edge (the current state's outputs still show on the abort cycle).
    // ----------------------------------------------------------------
    always_comb begin : fsm
        counter_nx = counter_ff;
        state_nx   = state_ff;

        if ((state_ff != IDLE) && sensor_generic) begin
            counter_nx = '0;
            state_nx   = IDLE;
        end else begin
            case (state_ff)
                IDLE: begin
                    counter_nx = '0;
                    if (start_q1) begin
                        // Launch into the first state of the operation.
                        case (operation_sel_ff)
                            3'b000, 3'b001: state_nx = HEAT;
                            3'b010, 3'b011: state_nx = BEAN_SEL;
                            3'b100:         state_nx = POWDER;
                            3'b101:         state_nx = POUR;
                            default:        state_nx = IDLE;
                        endcase
                    end else begin
                        state_nx = IDLE;
                    end
                end
                BEAN_SEL: begin
                    if (counter_ff >= (SEL_CYCLES - 1)) begin
                        counter_nx = '0;
                        state_nx   = GRIND;
                    end else begin
                        counter_nx = counter_ff + 1'b1;
                        state_nx   = BEAN_SEL;
                    end
                end
                GRIND: begin
                    if (counter_ff >= (grind_delay_ff - 1'b1)) begin
                        counter_nx = '0;
                        if (operation_sel_ff[0]) state_nx = POWDER;
                        else                     state_nx = HEAT;
                    end else begin
                        counter_nx = counter_ff + 1'b1;
                        state_nx   = GRIND;
                    end
                end
                HEAT: begin
                    if (counter_ff >= (heat_delay_ff - 1'b1)) begin
                        counter_nx = '0;
                        if (|operation_sel_ff[1:0]) state_nx = POWDER;
                        else                        state_nx = POUR;
                    end else begin
                        counter_nx = counter_ff + 1'b1;
                        state_nx   = HEAT;
                    end
                end
                POWDER: begin
                    if (counter_ff >= (POWDER_CYCLES - 1)) begin
                        counter_nx = '0;
                        state_nx   = POUR;
                    end else begin
                        counter_nx = counter_ff + 1'b1;
                        state_nx   = POWDER;
                    end
                end
                POUR: begin
                    if (counter_ff >= (pour_delay_ff - 1'b1)) begin
                        counter_nx = '0;
                        state_nx   = IDLE;
                    end else begin
                        counter_nx = counter_ff + 1'b1;
                        state_nx   = POUR;
                    end
                end
                default: begin
                    counter_nx = '0;
                    state_nx   = IDLE;
                end
            endcase
        end
    end

    // ----------------------------------------------------------------
    // Moore outputs (combinational on state_ff). o_bean_sel is one-hot
    // and held through BEAN_SEL and GRIND.
    // ----------------------------------------------------------------
    logic [NS_BEANS-1:0] bean_onehot;
    assign bean_onehot = ({{(NS_BEANS-1){1'b0}}, 1'b1}) << bean_sel_in_ff;

    always_comb begin : outputs
        o_bean_sel    = '0;
        o_grind_beans = 1'b0;
        o_use_powder  = 1'b0;
        o_heat_water  = 1'b0;
        o_pour_coffee = 1'b0;
        case (state_ff)
            BEAN_SEL: begin
                o_bean_sel = bean_onehot;
            end
            GRIND: begin
                o_bean_sel    = bean_onehot;
                o_grind_beans = 1'b1;
            end
            POWDER: begin
                o_use_powder = 1'b1;
            end
            HEAT: begin
                o_heat_water = 1'b1;
            end
            POUR: begin
                o_pour_coffee = 1'b1;
            end
            default: ; // IDLE: all zero
        endcase
    end

endmodule : coffee_machine
