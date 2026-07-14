`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: dac7554_ramp
// Description: DAC7554 channel-B SPI master + sawtooth ramp generator.
//              At init: powers down unused channels A/C/D (0xF000/F400/F600),
//              then repeatedly ramps channel B 0 -> 4095 and wraps to 0 using
//              write+update commands (0x9000 | code).  VOUTB drives the ADC
//              VCNTRL attenuation pin.
//
//              Host sets the ramp speed: step_cycles = clk cycles between
//              code increments.  0 = back-to-back SPI frames (~1.4 M steps/s,
//              full ramp in ~2.9 ms); 100_000 = one step per 1 ms (full ramp
//              in ~4.1 s); max 16.7M = one step per 167 ms.
//
//              SPI: mode 2 (CPOL=1, CPHA=0), gated 25 MHz SCLK from 100 MHz,
//              16-bit frames MSB first.  DIN is driven on the SCLK rising
//              edge; the DAC samples it on the falling edge.  /SYNC must stay
//              low for exactly the 16-bit frame and high >= 20 ns (t8) between
//              frames -- the GAP state gives 50 ns.
//////////////////////////////////////////////////////////////////////////////////

module dac7554_ramp (
    input  wire        clk,          // 100 MHz (clk_in domain)
    input  wire        rst,          // rst_sys
    input  wire [23:0] step_cycles,  // clk cycles between ramp steps (0 = max rate)
    input  wire        run,          // 0 = freeze the ramp at its current code
    output reg         dac_sync_n,
    output reg         dac_sclk,
    output reg         dac_din
);

    //--------------------------------------------------------------------------
    // SPI frame engine: shifts one 16-bit word per start pulse.
    //--------------------------------------------------------------------------
    localparam [1:0] SPI_IDLE  = 2'd0,
                     SPI_SYNC  = 2'd1,
                     SPI_SHIFT = 2'd2,
                     SPI_GAP   = 2'd3;

    reg [1:0]  spi_state = SPI_IDLE;
    reg [15:0] shreg;
    reg [4:0]  bitcnt;
    reg        div;                  // SCLK toggles every 2 clk -> 25 MHz
    reg [1:0]  gapcnt;

    reg        start;
    reg [15:0] word;
    wire       spi_busy = (spi_state != SPI_IDLE) || start;

    always @(posedge clk) begin
        if (rst) begin
            spi_state  <= SPI_IDLE;
            dac_sync_n <= 1'b1;
            dac_sclk   <= 1'b1;                    // CPOL = 1
            dac_din    <= 1'b0;
        end else begin
            div <= div + 1'b1;
            case (spi_state)
                SPI_IDLE: begin
                    dac_sync_n <= 1'b1;
                    dac_sclk   <= 1'b1;
                    if (start) begin
                        shreg     <= word;
                        bitcnt    <= 5'd16;
                        spi_state <= SPI_SYNC;
                    end
                end
                SPI_SYNC: begin                    // MSB out, then /SYNC low
                    dac_din    <= shreg[15];       // t4: 10 ns >= 4 ns min
                    dac_sync_n <= 1'b0;
                    div        <= 1'b0;
                    spi_state  <= SPI_SHIFT;
                end
                SPI_SHIFT: if (div) begin
                    div <= 1'b0;
                    if (dac_sclk) begin            // falling edge: DAC samples DIN
                        dac_sclk <= 1'b0;
                        bitcnt   <= bitcnt - 1'b1;
                    end else begin                 // rising edge: next bit out
                        dac_sclk <= 1'b1;
                        shreg    <= {shreg[14:0], 1'b0};
                        dac_din  <= shreg[14];
                        if (bitcnt == 5'd0) begin
                            gapcnt    <= 2'd3;
                            spi_state <= SPI_GAP;
                        end
                    end
                end
                SPI_GAP: begin                     // word latches on /SYNC rise
                    dac_sync_n <= 1'b1;
                    gapcnt     <= gapcnt - 1'b1;
                    if (gapcnt == 2'd0) spi_state <= SPI_IDLE;
                end
            endcase
        end
    end

    //--------------------------------------------------------------------------
    // Sequencer: power down A/C/D once, then ramp channel B forever.
    //--------------------------------------------------------------------------
    localparam [2:0] SEQ_WAIT = 3'd0,
                     SEQ_PD_A = 3'd1,
                     SEQ_PD_C = 3'd2,
                     SEQ_PD_D = 3'd3,
                     SEQ_RAMP = 3'd4;

    reg [2:0]  seq = SEQ_WAIT;
    reg [15:0] boot_dly;
    reg [11:0] code;
    reg [23:0] step_timer;
    reg        step_due;

    always @(posedge clk) begin
        if (rst) begin
            seq        <= SEQ_WAIT;
            boot_dly   <= 16'hFFFF;    // ~650 us settle before the first frame
            code       <= 12'd0;
            step_timer <= 24'd0;
            step_due   <= 1'b0;
            start      <= 1'b0;
            word       <= 16'h0000;
        end else begin
            start <= 1'b0;

            if (step_timer != 24'd0) step_timer <= step_timer - 1'b1;
            else                     step_due   <= 1'b1;

            case (seq)
                SEQ_WAIT: begin
                    boot_dly <= boot_dly - 1'b1;
                    if (boot_dly == 16'd0) seq <= SEQ_PD_A;
                end
                SEQ_PD_A: if (!spi_busy) begin
                    word <= 16'hF000;  start <= 1'b1;  seq <= SEQ_PD_C;
                end
                SEQ_PD_C: if (!spi_busy) begin
                    word <= 16'hF400;  start <= 1'b1;  seq <= SEQ_PD_D;
                end
                SEQ_PD_D: if (!spi_busy) begin
                    word <= 16'hF600;  start <= 1'b1;  seq <= SEQ_RAMP;
                end
                SEQ_RAMP: if (!spi_busy && step_due && run) begin
                    word       <= 16'h9000 | {4'h0, code};
                    start      <= 1'b1;
                    code       <= code + 1'b1;         // 4095 wraps to 0
                    step_timer <= step_cycles;
                    step_due   <= (step_cycles == 24'd0);
                end
            endcase
        end
    end

endmodule
