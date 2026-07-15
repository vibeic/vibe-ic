module fan_controller (
    input wire clk,                 // System clock
    input wire reset,               // Reset signal
    output reg fan_pwm_out,         // PWM output for fan control

    //APB signals
    input  wire         psel,       // Slave select
    input  wire         penable,    // Enable signal
    input  wire         pwrite,     // Write control
    input  wire [7:0]   paddr,      // Address bus
    input  wire [7:0]   pwdata,     // Write data bus
    output reg  [7:0]   prdata,     // Read data bus
    output reg          pready,     // Ready signal
    output reg          pslverr     // Slave error
);

    // ------------------------------------------------------------------
    // Register address map
    // ------------------------------------------------------------------
    localparam [7:0] ADDR_TEMP_LOW    = 8'h0a;
    localparam [7:0] ADDR_TEMP_MED    = 8'h0b;
    localparam [7:0] ADDR_TEMP_HIGH   = 8'h0c;
    localparam [7:0] ADDR_TEMP_ADC_IN = 8'h0f;

    // Duty-cycle counter load values (out of a 256-clock PWM period)
    localparam [7:0] DUTY_OFF = 8'd0;    // fan disabled (reset)
    localparam [7:0] DUTY_25  = 8'd64;   // 25%  : high 64,  low 192
    localparam [7:0] DUTY_50  = 8'd128;  // 50%  : high 128, low 128
    localparam [7:0] DUTY_75  = 8'd192;  // 75%  : high 192, low 64
    localparam [7:0] DUTY_100 = 8'd255;  // 100% : high 255, low 1

    // ------------------------------------------------------------------
    // Internal registers (names per specification)
    // ------------------------------------------------------------------
    reg [7:0] TEMP_LOW;        // 0x0a : max temperature considered "low"
    reg [7:0] TEMP_MED;        // 0x0b : max temperature considered "medium"
    reg [7:0] TEMP_HIGH;       // 0x0c : max temperature considered "high"
    reg [7:0] temp_adc_in;     // 0x0f : current temperature reading (ADC)

    reg [7:0] pwm_duty_cycle;  // current PWM duty (counter load value)
    reg [7:0] pwm_counter;     // free-running 8-bit PWM period counter

    // ------------------------------------------------------------------
    // Address decode (prepared during the setup phase - combinational)
    // ------------------------------------------------------------------
    wire addr_valid = (paddr == ADDR_TEMP_LOW ) ||
                      (paddr == ADDR_TEMP_MED ) ||
                      (paddr == ADDR_TEMP_HIGH) ||
                      (paddr == ADDR_TEMP_ADC_IN);

    // ------------------------------------------------------------------
    // APB write: performed in the access phase (psel & penable & pwrite).
    // An invalid address performs no register update (error is flagged
    // on pslverr instead).
    // ------------------------------------------------------------------
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            TEMP_LOW    <= 8'h00;
            TEMP_MED    <= 8'h00;
            TEMP_HIGH   <= 8'h00;
            temp_adc_in <= 8'h00;
        end else if (psel && penable && pwrite) begin
            case (paddr)
                ADDR_TEMP_LOW:    TEMP_LOW    <= pwdata;
                ADDR_TEMP_MED:    TEMP_MED    <= pwdata;
                ADDR_TEMP_HIGH:   TEMP_HIGH   <= pwdata;
                ADDR_TEMP_ADC_IN: temp_adc_in <= pwdata;
                default:          ; // invalid address: no write
            endcase
        end
    end

    // ------------------------------------------------------------------
    // APB response: zero-wait-state slave.
    //   - pready asserted only during the access phase
    //   - pslverr asserted during the access phase for invalid addresses
    //   - both cleared whenever the module is not selected (psel = 0)
    //   - prdata is a 0-cycle combinational read of the live registers
    // ------------------------------------------------------------------
    always @(*) begin
        pready  = psel && penable;
        pslverr = psel && penable && !addr_valid;
        prdata  = 8'h00;
        if (psel && !pwrite) begin
            case (paddr)
                ADDR_TEMP_LOW:    prdata = TEMP_LOW;
                ADDR_TEMP_MED:    prdata = TEMP_MED;
                ADDR_TEMP_HIGH:   prdata = TEMP_HIGH;
                ADDR_TEMP_ADC_IN: prdata = temp_adc_in;
                default:          prdata = 8'h00; // invalid address reads 0
            endcase
        end
    end

    // ------------------------------------------------------------------
    // Temperature-based fan speed selection.
    //   TEMP_x holds the MAXIMUM temperature considered as that band:
    //     temp <= TEMP_LOW              -> low    (25%)
    //     TEMP_LOW  < temp <= TEMP_MED  -> medium (50%)
    //     TEMP_MED  < temp <= TEMP_HIGH -> high   (75%)
    //     temp >  TEMP_HIGH             -> full   (100%)
    //   Reset disables the fan (pwm_duty_cycle = 0).
    // ------------------------------------------------------------------
    always @(posedge clk or posedge reset) begin
        if (reset)
            pwm_duty_cycle <= DUTY_OFF;
        else if (temp_adc_in <= TEMP_LOW)
            pwm_duty_cycle <= DUTY_25;
        else if (temp_adc_in <= TEMP_MED)
            pwm_duty_cycle <= DUTY_50;
        else if (temp_adc_in <= TEMP_HIGH)
            pwm_duty_cycle <= DUTY_75;
        else
            pwm_duty_cycle <= DUTY_100;
    end

    // ------------------------------------------------------------------
    // PWM period counter: free-running 0..255 (256-clock period).
    // ------------------------------------------------------------------
    always @(posedge clk or posedge reset) begin
        if (reset)
            pwm_counter <= 8'd0;
        else
            pwm_counter <= pwm_counter + 8'd1;
    end

    // ------------------------------------------------------------------
    // PWM output: high for pwm_duty_cycle clocks out of every 256.
    //   duty 64  -> high 64 / low 192
    //   duty 128 -> high 128 / low 128
    //   duty 192 -> high 192 / low 64
    //   duty 255 -> high 255 / low 1
    //   duty 0   -> output disabled (also holds 0 during reset)
    // ------------------------------------------------------------------
    always @(*) begin
        fan_pwm_out = (pwm_counter < pwm_duty_cycle);
    end

endmodule
