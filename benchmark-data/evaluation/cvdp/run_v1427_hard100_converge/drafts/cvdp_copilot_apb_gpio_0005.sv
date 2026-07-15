module cvdp_copilot_apb_gpio #(
  parameter GPIO_WIDTH = 8
)(
  // Clock and Reset Signals
  input logic pclk,       // Clock signal
  input logic preset_n,   // Active-low reset signal

  // APB Interface Inputs
  input logic psel,           // Peripheral select
  input logic [7:2] paddr,    // APB address bus (bits [7:2])
  input logic penable,        // Transfer control signal
  input logic pwrite,         // Write control signal
  input logic [31:0] pwdata,  // Write data bus

  // APB Interface Outputs
  output logic [31:0] prdata, // Read data bus
  output logic pready,        // Device ready signal
  output logic pslverr,       // Device error response

  // Bidirectional GPIO Interface
  inout wire [GPIO_WIDTH-1:0] gpio,       // Bidirectional GPIO pins

  // Interrupt Outputs
  output logic [GPIO_WIDTH-1:0] gpio_int, // Individual interrupt outputs
  output logic comb_int                   // Combined interrupt output
);

  // Signals for Read/Write Controls
  logic read_enable;                     // Read enable signal
  logic write_enable;                    // Write enable signal
  logic write_enable_reg_04;             // Write enable for Data Output register
  logic write_enable_reg_08;             // Write enable for Output Enable register
  logic write_enable_reg_0C;             // Write enable for Interrupt Enable register
  logic write_enable_reg_10;             // Write enable for Interrupt Type register
  logic write_enable_reg_14;             // Write enable for Interrupt Polarity register
  logic write_enable_reg_18;             // Write enable for Interrupt State register
  logic write_enable_reg_1C;             // Write enable for Direction Control register
  logic write_enable_reg_20;             // Write enable for Power Management register
  logic write_enable_reg_24;             // Write enable for Interrupt Reset register
  logic [GPIO_WIDTH-1:0] read_mux;       // Read data multiplexer
  logic [GPIO_WIDTH-1:0] read_mux_d1;    // Registered read data

  // Control Registers
  logic [GPIO_WIDTH-1:0] reg_dout;       // Data Output register
  logic [GPIO_WIDTH-1:0] reg_dout_en;    // Output Enable register
  logic [GPIO_WIDTH-1:0] reg_int_en;     // Interrupt Enable register
  logic [GPIO_WIDTH-1:0] reg_int_type;   // Interrupt Type register
  logic [GPIO_WIDTH-1:0] reg_int_pol;    // Interrupt Polarity register
  logic [GPIO_WIDTH-1:0] reg_int_state;  // Interrupt State register
  logic [GPIO_WIDTH-1:0] gpio_dir;       // Direction Control register (0: Input, 1: Output)
  logic reg_pwr_down;                    // Power Management register bit[0] (global power-down)

  // I/O Signal Path and Interrupt Logic
  logic [GPIO_WIDTH-1:0] data_in_sync1;            // First stage of input synchronization
  logic [GPIO_WIDTH-1:0] data_in_sync2;            // Second stage of input synchronization
  logic [GPIO_WIDTH-1:0] data_in_pol_adjusted;     // Polarity-adjusted input data
  logic [GPIO_WIDTH-1:0] data_in_pol_adjusted_dly; // Delayed version of polarity-adjusted input data
  logic [GPIO_WIDTH-1:0] edge_detect;              // Edge detection signals
  logic [GPIO_WIDTH-1:0] raw_int;                  // Raw interrupt signals
  logic [GPIO_WIDTH-1:0] int_masked;               // Masked interrupt signals
  logic [GPIO_WIDTH-1:0] clear_interrupt;          // Clear interrupt signals

  // Read and Write Control Signals
  assign read_enable = psel & (~pwrite); // Read enable
  assign write_enable = psel & (~penable) & pwrite; // Write enable

  // Write Enable Signals for Specific Registers
  // Global power-down masks writes to the normal control registers; the Power
  // Management register itself and the interrupt-status paths (Interrupt State
  // write-1-to-clear and the Interrupt Reset register) remain accessible so
  // software always has a path to re-enable the block and manage interrupts.
  assign write_enable_reg_04 = write_enable & (paddr[7:2] == 6'd1) & ~reg_pwr_down; // Address 0x04
  assign write_enable_reg_08 = write_enable & (paddr[7:2] == 6'd2) & ~reg_pwr_down; // Address 0x08
  assign write_enable_reg_0C = write_enable & (paddr[7:2] == 6'd3) & ~reg_pwr_down; // Address 0x0C
  assign write_enable_reg_10 = write_enable & (paddr[7:2] == 6'd4) & ~reg_pwr_down; // Address 0x10
  assign write_enable_reg_14 = write_enable & (paddr[7:2] == 6'd5) & ~reg_pwr_down; // Address 0x14
  assign write_enable_reg_18 = write_enable & (paddr[7:2] == 6'd6);                 // Address 0x18
  assign write_enable_reg_1C = write_enable & (paddr[7:2] == 6'd7) & ~reg_pwr_down; // Address 0x1C
  assign write_enable_reg_20 = write_enable & (paddr[7:2] == 6'd8);                 // Address 0x20
  assign write_enable_reg_24 = write_enable & (paddr[7:2] == 6'd9);                 // Address 0x24

  // Write Operations for Control Registers

  // Data Output Register (reg_dout)
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      reg_dout <= {GPIO_WIDTH{1'b0}};
    else if (write_enable_reg_04)
      reg_dout <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Output Enable Register (reg_dout_en)
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      reg_dout_en <= {GPIO_WIDTH{1'b0}};
    else if (write_enable_reg_08)
      reg_dout_en <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Interrupt Enable Register (reg_int_en)
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      reg_int_en <= {GPIO_WIDTH{1'b0}};
    else if (write_enable_reg_0C)
      reg_int_en <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Interrupt Type Register (reg_int_type)
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      reg_int_type <= {GPIO_WIDTH{1'b0}};
    else if (write_enable_reg_10)
      reg_int_type <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Interrupt Polarity Register (reg_int_pol)
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      reg_int_pol <= {GPIO_WIDTH{1'b0}};
    else if (write_enable_reg_14)
      reg_int_pol <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Direction Control Register (gpio_dir) - updates synchronized to pclk
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      gpio_dir <= {GPIO_WIDTH{1'b0}}; // All pins default to input for safe start-up
    else if (write_enable_reg_1C)
      gpio_dir <= pwdata[(GPIO_WIDTH-1):0];
  end

  // Power Management Register (reg_pwr_down) - bit[0] only, reserved bits ignored
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      reg_pwr_down <= 1'b0; // Normal operation after reset
    else if (write_enable_reg_20)
      reg_pwr_down <= pwdata[0];
  end

  // Read Operation: Multiplexing Register Data Based on Address
  always_comb begin
    case (paddr[7:2])
      6'd0: read_mux = data_in_sync2;   // Input Data Register at address 0x00
      6'd1: read_mux = reg_dout;        // Data Output Register at address 0x04
      6'd2: read_mux = reg_dout_en;     // Output Enable Register at address 0x08
      6'd3: read_mux = reg_int_en;      // Interrupt Enable Register at address 0x0C
      6'd4: read_mux = reg_int_type;    // Interrupt Type Register at address 0x10
      6'd5: read_mux = reg_int_pol;     // Interrupt Polarity Register at address 0x14
      6'd6: read_mux = reg_int_state;   // Interrupt State Register at address 0x18
      6'd7: read_mux = gpio_dir;        // Direction Control Register at address 0x1C
      6'd8: begin                       // Power Management Register at address 0x20
        read_mux = {GPIO_WIDTH{1'b0}};
        read_mux[0] = reg_pwr_down;
      end
      default: read_mux = {GPIO_WIDTH{1'b0}}; // Default to zeros if address is invalid
    endcase
  end

  // Registering Read Data for Timing Alignment
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n)
      read_mux_d1 <= {GPIO_WIDTH{1'b0}};
    else
      read_mux_d1 <= read_mux;
  end

  // Output Read Data to APB Interface
  assign prdata = (read_enable) ? {{(32-GPIO_WIDTH){1'b0}}, read_mux_d1} : {32{1'b0}};
  assign pready = 1'b1; // Always ready
  assign pslverr = 1'b0; // No error

  // Bidirectional GPIO Pin Drivers
  // A pin is actively driven only when its Direction Control bit configures it
  // as an output and the block is not globally powered down; otherwise the pin
  // is released to high-impedance (safe input configuration / power-down).
  generate
    genvar g;
    for (g = 0; g < GPIO_WIDTH; g = g + 1) begin : g_gpio_drive
      assign gpio[g] = (gpio_dir[g] & ~reg_pwr_down) ? reg_dout[g] : 1'bz;
    end
  endgenerate

  // Input Synchronization to Avoid Metastability
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n) begin
      data_in_sync1 <= {GPIO_WIDTH{1'b0}};
      data_in_sync2 <= {GPIO_WIDTH{1'b0}};
    end else begin
      data_in_sync1 <= gpio;
      data_in_sync2 <= data_in_sync1;
    end
  end

  // Interrupt Logic

  // Adjusting Input Data Based on Interrupt Polarity
  assign data_in_pol_adjusted = data_in_sync2 ^ reg_int_pol; // Polarity adjustment

  // Registering Polarity-Adjusted Input Data and Delaying for Edge Detection
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n) begin
      data_in_pol_adjusted_dly <= {GPIO_WIDTH{1'b0}};
    end else begin
      data_in_pol_adjusted_dly <= data_in_pol_adjusted;
    end
  end

  // Edge Detection Logic for Interrupts
  assign edge_detect = data_in_pol_adjusted & (~data_in_pol_adjusted_dly); // Rising edge detection

  // Selecting Interrupt Type (Edge or Level-Triggered)
  assign raw_int = (reg_int_type & edge_detect) | (~reg_int_type & data_in_pol_adjusted); // Interrupt source

  // Applying Interrupt Enable Mask (global power-down suppresses new interrupts)
  assign int_masked = raw_int & reg_int_en & {GPIO_WIDTH{~reg_pwr_down}}; // Masked interrupts

  // Clear Interrupt Signals (Interrupt State write-1-to-clear at 0x18 and the
  // software-controlled Interrupt Reset Register at 0x24)
  assign clear_interrupt = pwdata[GPIO_WIDTH-1:0] &
                           ({GPIO_WIDTH{write_enable_reg_18}} |
                            {GPIO_WIDTH{write_enable_reg_24}});

  // Updating Interrupt State Register (Corrected Logic)
  always_ff @(posedge pclk or negedge preset_n) begin
    if (~preset_n) begin
      reg_int_state <= {GPIO_WIDTH{1'b0}};
    end else begin
      integer i;
      for (i = 0; i < GPIO_WIDTH; i = i + 1) begin
        if (reg_int_type[i]) begin
          // Edge-triggered interrupt
          if (clear_interrupt[i]) begin
            reg_int_state[i] <= 1'b0;
          end else if (int_masked[i]) begin
            reg_int_state[i] <= 1'b1;
          end
        end else begin
          // Level-triggered interrupt
          reg_int_state[i] <= int_masked[i];
        end
      end
    end
  end

  // Connecting Interrupt Outputs
  assign gpio_int = reg_int_state;     // Individual interrupt outputs
  assign comb_int = |reg_int_state;    // Combined interrupt output

endmodule
