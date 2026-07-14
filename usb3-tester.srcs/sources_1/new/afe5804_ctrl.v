//==============================================================================
// AFE5804 controller - Alchitry Au V2 (XC7A35T-2FTG256I)
//
// Boots, initialises the AFE, auto-aligns the LVDS word boundary using the
// sync pattern, then idles ready for capture.  No manual alignment needed.
//
// LEDs
//   [7] FPGA heartbeat
//   [6] SPI write fired (~80 ms flash)
//   [5] LCLK alive
//   [4] FCLK alive
//   [3] OUT1 activity
//   [2:0] phase   001 = reset   010 = t7 wait   100 = aligning
//                 101 = LOCKED (LED2+LED0)      110 = ALIGN FAILED (LED2+LED1)
//
// UART @ 2 Mbaud, 8N1
//   i init      R hw reset+init   K re-align
//   d deskew    s sync            m ramp        n patterns off
//   p partial-PD  c complete-PD   o PD off
//   h LVDS 7.5mA  l LVDS 3.5mA    v TGC-I 30dB  L TGC-II
//   b MSB-first   B LSB-first
//   7/8 CH2-8 off (two candidate bit maps)      9 all channels on
//   A eye scan (run after 'd' or 's')
//   + - dat_tap   > < fclk_tap
//   r raw 32-word dump   g assembled 32-sample dump
//   C 8192-sample deep capture -> 16384 raw bytes, little-endian
//   wAADDDD raw 24-bit SPI write
//==============================================================================

//------------------------------------------------------------------------------
module uart_rx #(
  parameter CLK_HZ = 100_000_000,
  parameter BAUD   = 115200
)(
  input  wire       clk,
  input  wire       rst,
  input  wire       rx,
  output reg  [7:0] data,
  output reg        valid
);
  localparam DIV = CLK_HZ / BAUD;
  localparam S_IDLE = 2'd0, S_START = 2'd1, S_DATA = 2'd2, S_STOP = 2'd3;

  reg  [1:0]  st   = S_IDLE;
  reg  [2:0]  sync = 3'b111;
  reg  [15:0] cnt  = 0;
  reg  [2:0]  bitn = 0;
  reg  [7:0]  sh   = 0;

  always @(posedge clk) begin
    sync  <= {sync[1:0], rx};
    valid <= 1'b0;
    if (rst) begin
      st <= S_IDLE; cnt <= 0; bitn <= 0;
    end else begin
      case (st)
        S_IDLE:
          if (!sync[2]) begin cnt <= 0; st <= S_START; end
        S_START:
          if (cnt == DIV/2 - 1) begin
            cnt <= 0;
            if (!sync[2]) begin bitn <= 0; st <= S_DATA; end
            else               st <= S_IDLE;          // glitch, not a start bit
          end else cnt <= cnt + 1'b1;
        S_DATA:
          if (cnt == DIV - 1) begin
            cnt <= 0;
            sh  <= {sync[2], sh[7:1]};                // LSB first
            if (bitn == 3'd7) st <= S_STOP;
            else              bitn <= bitn + 1'b1;
          end else cnt <= cnt + 1'b1;
        S_STOP:
          if (cnt == DIV - 1) begin
            cnt <= 0; st <= S_IDLE;
            if (sync[2]) begin data <= sh; valid <= 1'b1; end
          end else cnt <= cnt + 1'b1;
      endcase
    end
  end
endmodule


//------------------------------------------------------------------------------
module uart_tx #(
  parameter CLK_HZ = 100_000_000,
  parameter BAUD   = 115200
)(
  input  wire       clk,
  input  wire       rst,
  input  wire [7:0] data,
  input  wire       send,
  output wire       busy,
  output reg        tx
);
  localparam DIV = CLK_HZ / BAUD;

  reg [9:0]  sh     = 10'h3FF;
  reg [15:0] cnt    = 0;
  reg [3:0]  n      = 0;
  reg        busy_r = 1'b0;

  assign busy = busy_r;

  always @(posedge clk) begin
    if (rst) begin
      busy_r <= 1'b0; tx <= 1'b1; cnt <= 0; n <= 0;
    end else if (!busy_r) begin
      tx <= 1'b1;
      if (send) begin
        sh <= {1'b1, data, 1'b0};                     // stop, data, start
        busy_r <= 1'b1; cnt <= 0; n <= 0;
      end
    end else begin
      tx <= sh[0];
      if (cnt == DIV - 1) begin
        cnt <= 0;
        sh  <= {1'b1, sh[9:1]};
        if (n == 4'd9) busy_r <= 1'b0;
        else           n <= n + 1'b1;
      end else cnt <= cnt + 1'b1;
    end
  end
endmodule

module spi_master24 #(
  parameter CLK_HZ  = 100_000_000,
  parameter SCLK_HZ = 1_000_000                       // AFE max 20 MHz
)(
  input  wire        clk,
  input  wire        rst,
  input  wire        start,
  input  wire [23:0] word,                            // {addr[7:0], data[15:0]}
  output wire        busy,
  output reg         cs_n,
  output reg         sclk,
  output reg         sdata
);
  localparam HALF = CLK_HZ / (2 * SCLK_HZ);
  localparam S_IDLE = 3'd0, S_SETUP = 3'd1, S_LOW = 3'd2,
             S_HIGH = 3'd3, S_HOLD  = 3'd4;

  reg [2:0]  st     = S_IDLE;
  reg [15:0] cnt    = 0;
  reg [4:0]  bitn   = 0;
  reg [23:0] sh     = 0;
  reg        busy_r = 1'b0;

  assign busy = busy_r;

  always @(posedge clk) begin
    if (rst) begin
      st <= S_IDLE; cs_n <= 1'b1; sclk <= 1'b0; sdata <= 1'b0;
      busy_r <= 1'b0; cnt <= 0; bitn <= 0;
    end else begin
      case (st)
        S_IDLE: begin
          cs_n <= 1'b1; sclk <= 1'b0; busy_r <= 1'b0;
          if (start) begin
            sh <= word; bitn <= 5'd23; cnt <= 0;
            cs_n <= 1'b0; busy_r <= 1'b1;             // t6: CS fall -> SCLK rise
            st <= S_SETUP;
          end
        end
        S_SETUP: begin                                 // honour t6 >= 8 ns
          sdata <= sh[23];
          if (cnt == HALF-1) begin cnt <= 0; st <= S_LOW; end
          else cnt <= cnt + 1'b1;
        end
        S_LOW: begin                                   // data valid, SCLK low
          sdata <= sh[23];
          sclk  <= 1'b0;
          if (cnt == HALF-1) begin cnt <= 0; sclk <= 1'b1; st <= S_HIGH; end
          else cnt <= cnt + 1'b1;
        end
        S_HIGH: begin                                  // SCLK high: AFE latches
          if (cnt == HALF-1) begin
            cnt  <= 0;
            sclk <= 1'b0;
            sh   <= {sh[22:0], 1'b0};
            if (bitn == 5'd0) st <= S_HOLD;
            else begin bitn <= bitn - 1'b1; st <= S_LOW; end
          end else cnt <= cnt + 1'b1;
        end
        S_HOLD: begin                                  // t7 >= 8 ns before CS rise
          if (cnt == HALF-1) begin
            cnt <= 0; cs_n <= 1'b1; busy_r <= 1'b0; st <= S_IDLE;
          end else cnt <= cnt + 1'b1;
        end
      endcase
    end
  end
endmodule



module afe5804_ctrl #(
  parameter CLK_HZ = 100_000_000,
  parameter BAUD   = 2_000_000
)(
  input  wire       clk,
  input  wire       rst_n,
  input  wire       usb_rx,
  output wire       usb_tx,
  output wire [7:0] led,

  input  wire       lclk_p, lclk_n,
  input  wire       fclk_p, fclk_n,
  input  wire       out1_p, out1_n,

  output wire       afe_sclk,
  output wire       afe_cs_n,
  output wire       afe_sdata,
  output reg        afe_rst_n,

  // continuous sample stream out (stream_clk = LVDS rx_div, 80 MHz)
  output wire        stream_clk,
  output wire [11:0] stream_data,
  output wire        stream_valid
);

  //--------------------------------------------------------------------------
  // Calibration constants
  //--------------------------------------------------------------------------
  // Re-measure with the fixed scan: press 'd' then 'A'.  Expect a narrow fail
  // zone; the scanner centres the pass window automatically.  Put the number
  // it reports here.  (The old value of 21/26 came from a scan whose metric
  // was rotation-sensitive and cannot be trusted.)
  localparam [4:0] ALIGN_TAP = 5'd14;      // <-- Tested using script, center of eye
  localparam [3:0] MAX_SLIPS = 4'd12;

  // 0x42: D15,D7 forced '1' | D0 DIFF_CLK | D2 EN_DCC | D3 EXT_REF_VCM
  //       D6:D5 PHASE_DDR
  localparam [15:0] REG42_VAL  = 16'h8081;
  // 0x46: D15,D9 forced '1' | D3 MSB_FIRST
  localparam [15:0] REG46_LSB  = 16'h8200;
  localparam [15:0] REG46_MSB  = 16'h8208;
  // 0x11: ILVDS_DAT[10:8]/FRAME[6:4]/LCLK[2:0]; 100 = 7.5 mA
  localparam [15:0] REG11_HI   = 16'h0444;
  localparam [15:0] REG11_LO   = 16'h0000;
  // 0x25: D6 EN_RAMP | D5 DUALCUSTOM | D4 SINGLE_CUSTOM | D1:D0 CUSTOM1<11:10>
  localparam [15:0] REG25_OFF  = 16'h0000;
  localparam [15:0] REG25_RAMP = 16'h0040;

  localparam integer US       = CLK_HZ / 1_000_000;
  localparam integer T_RSTLOW = 1_000  * US;
  localparam integer T7       = 15_000 * US;
  localparam integer T_GAP    = 4      * US;
  localparam integer T_SETTLE = 100_000;     // 1 ms @ 100 MHz

  //--------------------------------------------------------------------------
  // Init ROM.  addr 0xFF = delay(us), 0xFE = end.
  // 0x42 first - nothing works until the clock input is differential.
  // No S_RST anywhere: it would clear DIFF_CLK.
  //--------------------------------------------------------------------------
  reg [23:0] rom [0:15];
  initial begin
    rom[ 0] = {8'h42, REG42_VAL};
    rom[ 1] = {8'hFF, 16'd300};      // PLL relock
    rom[ 2] = {8'h01, 16'h0010};     // TI-required LVDS/jitter block
    rom[ 3] = {8'hD1, 16'h0140};
    rom[ 4] = {8'hDA, 16'h0001};
    rom[ 5] = {8'hE1, 16'h0020};
    rom[ 6] = {8'h02, 16'h0080};
    rom[ 7] = {8'h01, 16'h0000};
    rom[ 8] = {8'h0F, 16'h0000};     // <-- set to 00F7 or 00FE for CH1-only
    rom[ 9] = {8'h11, REG11_LO};
    rom[10] = {8'h16, 16'h00DB};     // VCA: TGC I, PGA 30 dB, LPF 12.5 MHz
    rom[11] = {8'hFF, 16'd10};
    rom[12] = {8'h45, 16'h0000};
    rom[13] = {8'h25, REG25_OFF};
    rom[14] = {8'hFE, 16'h0000};
    rom[15] = {8'hFE, 16'h0000};
  end

  //--------------------------------------------------------------------------
  reg [2:0] rst_sync = 3'b111;
  wire      rst = rst_sync[2];
  always @(posedge clk) rst_sync <= {rst_sync[1:0], ~rst_n};

  //--------------------------------------------------------------------------
  // afe_rx
  //--------------------------------------------------------------------------
  reg         bitslip_req = 1'b0;
  reg  [4:0]  dat_tap     = 5'd0;
  reg  [4:0]  fclk_tap    = 5'd0;
  reg         tap_load    = 1'b0;
  reg         scan_clr    = 1'b0;
  reg         cap_req     = 1'b0;
  reg         cap_raw     = 1'b0;
  reg         deep_req    = 1'b0;
  reg  [4:0]  rd_addr     = 5'd0;
  reg  [12:0] deep_addr   = 13'd0;

  wire        cap_done, deep_done;
  wire [15:0] rd_data, deep_data;
  wire        err_dat, err_fclk;
  wire        lclk_alive, fclk_alive, out1_alive, idelay_rdy;

  afe_rx u_rx (
    .sys_clk(clk), .rst(rst),
    .lclk_p(lclk_p), .lclk_n(lclk_n),
    .fclk_p(fclk_p), .fclk_n(fclk_n),
    .out1_p(out1_p), .out1_n(out1_n),
    .bitslip_req(bitslip_req),
    .dat_tap(dat_tap), .fclk_tap(fclk_tap), .tap_load(tap_load),
    .scan_clr(scan_clr),
    .cap_req(cap_req), .cap_raw(cap_raw), .cap_done(cap_done),
    .rd_addr(rd_addr), .rd_data(rd_data),
    .deep_req(deep_req), .deep_done(deep_done),
    .deep_addr(deep_addr), .deep_data(deep_data),
    .err_dat(err_dat), .err_fclk(err_fclk),
    .lclk_alive(lclk_alive), .fclk_alive(fclk_alive), .out1_alive(out1_alive),
    .idelay_rdy(idelay_rdy),
    .samp_clk(stream_clk), .samp_data(stream_data), .samp_valid(stream_valid)
  );

  //--------------------------------------------------------------------------
  // UART / SPI
  //--------------------------------------------------------------------------
  wire [7:0]  rx_data;
  wire        rx_valid, tx_busy, spi_busy;
  reg  [7:0]  tx_data;
  reg         tx_send   = 1'b0;
  reg         spi_start = 1'b0;
  reg  [23:0] spi_word  = 24'd0;

  uart_rx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_uart_rx (
    .clk(clk), .rst(rst), .rx(usb_rx), .data(rx_data), .valid(rx_valid));

  uart_tx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_uart_tx (
    .clk(clk), .rst(rst), .data(tx_data), .send(tx_send),
    .busy(tx_busy), .tx(usb_tx));

  spi_master24 #(.CLK_HZ(CLK_HZ), .SCLK_HZ(1_000_000)) u_spi (
    .clk(clk), .rst(rst), .start(spi_start), .word(spi_word),
    .busy(spi_busy), .cs_n(afe_cs_n), .sclk(afe_sclk), .sdata(afe_sdata));

  //--------------------------------------------------------------------------
  // LEDs
  //--------------------------------------------------------------------------
  reg [25:0] hb = 26'd0;
  always @(posedge clk) hb <= hb + 1'b1;

  reg [22:0] spi_act = 23'd0;
  always @(posedge clk) begin
    if (spi_busy)          spi_act <= 23'h7F_FFFF;
    else if (spi_act != 0) spi_act <= spi_act - 1'b1;
  end

  reg [2:0] ph = 3'b000;
  assign led = { hb[25], (spi_act != 0), lclk_alive, fclk_alive,
                 out1_alive, ph };

  //--------------------------------------------------------------------------
  function [3:0] hexval(input [7:0] c);
    begin
      if      (c >= 8'h30 && c <= 8'h39) hexval = c - 8'h30;
      else if (c >= 8'h41 && c <= 8'h46) hexval = c - 8'h37;
      else if (c >= 8'h61 && c <= 8'h66) hexval = c - 8'h57;
      else                               hexval = 4'h0;
    end
  endfunction

  function ishex(input [7:0] c);
    begin
      ishex = (c >= 8'h30 && c <= 8'h39) ||
              (c >= 8'h41 && c <= 8'h46) ||
              (c >= 8'h61 && c <= 8'h66);
    end
  endfunction

  function [7:0] hexchr(input [3:0] n);
    begin
      hexchr = (n < 4'd10) ? (8'h30 + n) : (8'h37 + n);
    end
  endfunction

  //--------------------------------------------------------------------------
  // Sequencer
  //--------------------------------------------------------------------------
  localparam S_RSTLOW = 5'd0,  S_WAIT7 = 5'd1,  S_FETCH = 5'd2,  S_DELAY = 5'd3,
             S_ISSUE  = 5'd4,  S_WAITSP= 5'd5,  S_GAP   = 5'd6,  S_IDLE  = 5'd7,
             S_RAW    = 5'd8,  S_ECHO1 = 5'd9,  S_ECHO2 = 5'd10, S_ECHO3 = 5'd11,
             S_CAPW   = 5'd12, S_DUMP  = 5'd13,
             S_SCAN   = 5'd14, S_SFIND = 5'd15, S_SPRNT = 5'd16,
             A_SYNC   = 5'd17, A_TAP   = 5'd18, A_CLR   = 5'd19,
             A_CHK    = 5'd20, A_SLIP  = 5'd21, A_OFF   = 5'd22,
             S_DCAP   = 5'd23, S_DRD   = 5'd24, S_DLO   = 5'd25, S_DHI = 5'd26;

  reg [4:0]  seq       = S_RSTLOW;
  reg [4:0]  ret_state = S_ECHO1;
  reg [3:0]  romi      = 4'd0;
  reg [31:0] timer     = 32'd0;
  reg [15:0] delay_us  = 16'd0;
  reg        from_rom  = 1'b1;
  reg [7:0]  echo_ch   = 8'h3F;
  reg [2:0]  rawcnt    = 3'd0;
  reg [23:0] rawreg    = 24'd0;
  reg [2:0]  col       = 3'd0;
  reg        dlat      = 1'b0;
  reg [3:0]  slips     = 4'd0;

  // eye scan
  reg [4:0]  scan_tap  = 5'd0;
  reg [31:0] map_d     = 32'd0;
  reg [1:0]  scan_ph   = 2'd0;
  reg [5:0]  j         = 6'd0;
  reg [5:0]  cur_len   = 6'd0;
  reg [4:0]  cur_start = 5'd0;
  reg [5:0]  best_len  = 6'd0;
  reg [4:0]  best_tap  = 5'd0;

  wire [23:0] rw = rom[romi];

  always @(posedge clk) begin
    spi_start   <= 1'b0;
    tx_send     <= 1'b0;
    cap_req     <= 1'b0;
    deep_req    <= 1'b0;
    tap_load    <= 1'b0;
    bitslip_req <= 1'b0;
    scan_clr    <= 1'b0;

    if (rst) begin
      seq <= S_RSTLOW; timer <= 0; romi <= 0; from_rom <= 1'b1;
      afe_rst_n <= 1'b0; ph <= 3'b000; rawcnt <= 0;
    end else begin
      case (seq)

        S_RSTLOW: begin
          afe_rst_n <= 1'b0; ph <= 3'b001;
          if (timer == T_RSTLOW) begin
            timer <= 0; afe_rst_n <= 1'b1; seq <= S_WAIT7;
          end else timer <= timer + 1'b1;
        end

        S_WAIT7: begin
          ph <= 3'b010;
          if (timer == T7) begin
            timer <= 0; romi <= 0; from_rom <= 1'b1; seq <= S_FETCH;
          end else timer <= timer + 1'b1;
        end

        S_FETCH: begin
          if (rw[23:16] == 8'hFE) begin
            ph <= 3'b100; seq <= A_SYNC;          // -> auto-align
          end else if (rw[23:16] == 8'hFF) begin
            delay_us <= rw[15:0]; timer <= 0; seq <= S_DELAY;
          end else begin
            spi_word <= rw; spi_start <= 1'b1; seq <= S_WAITSP;
          end
        end

        S_DELAY: begin
          if (delay_us == 0) begin
            romi <= romi + 1'b1; seq <= S_FETCH;
          end else if (timer == US - 1) begin
            timer <= 0; delay_us <= delay_us - 1'b1;
          end else timer <= timer + 1'b1;
        end

        S_ISSUE:  begin spi_start <= 1'b1; seq <= S_WAITSP; end

        S_WAITSP: if (!spi_busy && !spi_start) begin timer <= 0; seq <= S_GAP; end

        S_GAP: begin
          if (timer == T_GAP) begin
            timer <= 0;
            if (from_rom) begin romi <= romi + 1'b1; seq <= S_FETCH; end
            else                seq <= ret_state;
          end else timer <= timer + 1'b1;
        end

        //==================== auto word alignment ==========================
        A_SYNC: begin
          spi_word  <= {8'h45, 16'h0002};        // sync pattern on
          from_rom  <= 1'b0;
          ret_state <= A_TAP;
          slips     <= 4'd0;
          ph        <= 3'b100;
          seq       <= S_ISSUE;
        end

        A_TAP: begin
          dat_tap  <= ALIGN_TAP;
          fclk_tap <= ALIGN_TAP;
          tap_load <= 1'b1;
          timer    <= 0;
          seq      <= A_CLR;
        end

        A_CLR: begin
          if (timer == T_SETTLE) begin
            timer <= 0; scan_clr <= 1'b1; seq <= A_CHK;
          end else timer <= timer + 1'b1;
        end

        A_CHK: begin
          if (timer == T_SETTLE) begin
            timer <= 0;
            if (!err_fclk)              seq <= A_OFF;      // aligned
            else if (slips == MAX_SLIPS) begin
              ph <= 3'b110; seq <= S_IDLE;                 // failed
            end else                    seq <= A_SLIP;
          end else timer <= timer + 1'b1;
        end

        A_SLIP: begin
          bitslip_req <= 1'b1;
          slips       <= slips + 1'b1;
          timer       <= 0;
          seq         <= A_CLR;
        end

        A_OFF: begin
          spi_word  <= {8'h45, 16'h0000};        // patterns off
          from_rom  <= 1'b0;
          ret_state <= S_IDLE;
          ph        <= 3'b101;                   // LOCKED
          seq       <= S_ISSUE;
        end

        //==================== idle / commands =============================
        S_IDLE: begin
          if (rx_valid) begin
            echo_ch   <= rx_data;
            from_rom  <= 1'b0;
            ret_state <= S_ECHO1;
            case (rx_data)
              8'h69: begin romi <= 0; from_rom <= 1'b1; seq <= S_FETCH; end   // i
              8'h52: begin timer <= 0; seq <= S_RSTLOW; end                   // R
              8'h4B: begin seq <= A_SYNC; end                                 // K
              8'h64: begin spi_word <= {8'h45, 16'h0001};   seq <= S_ISSUE; end // d
              8'h73: begin spi_word <= {8'h45, 16'h0002};   seq <= S_ISSUE; end // s
              8'h6D: begin spi_word <= {8'h25, REG25_RAMP}; seq <= S_ISSUE; end // m
              8'h6E: begin spi_word <= {8'h45, 16'h0000};   seq <= S_ISSUE; end // n
              8'h70: begin spi_word <= {8'h0F, 16'h0100};   seq <= S_ISSUE; end // p
              8'h63: begin spi_word <= {8'h0F, 16'h0200};   seq <= S_ISSUE; end // c
              8'h6F: begin spi_word <= {8'h0F, 16'h0000};   seq <= S_ISSUE; end // o
              8'h68: begin spi_word <= {8'h11, REG11_HI};   seq <= S_ISSUE; end // h
              8'h6C: begin spi_word <= {8'h11, REG11_LO};   seq <= S_ISSUE; end // l
              8'h76: begin spi_word <= {8'h16, 16'h00DB};   seq <= S_ISSUE; end // v
              8'h4C: begin spi_word <= {8'h16, 16'h00EB};   seq <= S_ISSUE; end // L
              8'h62: begin spi_word <= {8'h46, REG46_MSB};  seq <= S_ISSUE; end // b
              8'h42: begin spi_word <= {8'h46, REG46_LSB};  seq <= S_ISSUE; end // B
              8'h37: begin spi_word <= {8'h0F, 16'h00F7};   seq <= S_ISSUE; end // 7
              8'h38: begin spi_word <= {8'h0F, 16'h00FE};   seq <= S_ISSUE; end // 8
              8'h39: begin spi_word <= {8'h0F, 16'h0000};   seq <= S_ISSUE; end // 9
              8'h2B: begin dat_tap  <= dat_tap  + 1'b1; tap_load <= 1'b1; seq <= S_ECHO1; end // +
              8'h2D: begin dat_tap  <= dat_tap  - 1'b1; tap_load <= 1'b1; seq <= S_ECHO1; end // -
              8'h3E: begin fclk_tap <= fclk_tap + 1'b1; tap_load <= 1'b1; seq <= S_ECHO1; end // >
              8'h3C: begin fclk_tap <= fclk_tap - 1'b1; tap_load <= 1'b1; seq <= S_ECHO1; end // 
              8'h53: begin bitslip_req <= 1'b1; seq <= S_ECHO1; end                           // S
              8'h72: begin cap_raw <= 1'b1; cap_req <= 1'b1; timer <= 0; seq <= S_CAPW; end   // r
              8'h67: begin cap_raw <= 1'b0; cap_req <= 1'b1; timer <= 0; seq <= S_CAPW; end   // g
              8'h43: begin deep_req <= 1'b1; timer <= 0; seq <= S_DCAP; end                   // C
              8'h41: begin                                                                    // A
                       scan_tap <= 0; map_d <= 0; scan_ph <= 0; timer <= 0;
                       best_len <= 0; best_tap <= 0; cur_len <= 0; j <= 0;
                       dat_tap  <= 0; fclk_tap <= 0; tap_load <= 1'b1;
                       seq <= S_SCAN;
                     end
              8'h77: begin rawcnt <= 0; seq <= S_RAW; end                                     // w
              default: seq <= S_ECHO1;
            endcase
          end
        end

        S_RAW: begin
          if (rx_valid) begin
            if (ishex(rx_data)) begin
              rawreg <= {rawreg[19:0], hexval(rx_data)};
              if (rawcnt == 3'd5) begin
                spi_word  <= {rawreg[19:0], hexval(rx_data)};
                echo_ch   <= 8'h77;
                from_rom  <= 1'b0;
                ret_state <= S_ECHO1;
                seq       <= S_ISSUE;
              end else rawcnt <= rawcnt + 1'b1;
            end else begin
              echo_ch <= 8'h21; seq <= S_ECHO1;
            end
          end
        end

        //==================== 32-word dump ================================
        S_CAPW: begin
          if (cap_done) begin
            rd_addr <= 0; col <= 0; seq <= S_DUMP;
          end else if (timer == 32'd10_000_000) begin
            timer <= 0; echo_ch <= 8'h3F; seq <= S_ECHO1;   // '?' timeout
          end else timer <= timer + 1'b1;
        end

        S_DUMP: begin
          if (!tx_busy && !tx_send) begin
            case (col)
              3'd0: begin tx_data <= hexchr(rd_data[15:12]); tx_send <= 1'b1; col <= 3'd1; end
              3'd1: begin tx_data <= hexchr(rd_data[11: 8]); tx_send <= 1'b1; col <= 3'd2; end
              3'd2: begin tx_data <= hexchr(rd_data[ 7: 4]); tx_send <= 1'b1; col <= 3'd3; end
              3'd3: begin tx_data <= hexchr(rd_data[ 3: 0]); tx_send <= 1'b1; col <= 3'd4; end
              3'd4: begin tx_data <= 8'h0D;                  tx_send <= 1'b1; col <= 3'd5; end
              3'd5: begin
                      tx_data <= 8'h0A; tx_send <= 1'b1; col <= 3'd0;
                      if (rd_addr == 5'd31) seq <= S_IDLE;
                      else                  rd_addr <= rd_addr + 1'b1;
                    end
            endcase
          end
        end

        //==================== eye scan ====================================
        S_SCAN: begin
          case (scan_ph)
            2'd0: if (timer == T_SETTLE) begin              // settle
                    timer <= 0; scan_clr <= 1'b1; scan_ph <= 2'd1;
                  end else timer <= timer + 1'b1;
            2'd1: if (timer == T_SETTLE) begin              // observe
                    timer <= 0; scan_ph <= 2'd2;
                  end else timer <= timer + 1'b1;
            2'd2: begin
                    map_d[scan_tap] <= ~err_dat;            // stability metric
                    if (scan_tap == 5'd31) begin
                      j <= 0; cur_len <= 0; seq <= S_SFIND;
                    end else begin
                      scan_tap <= scan_tap + 1'b1;
                      dat_tap  <= scan_tap + 1'b1;
                      fclk_tap <= scan_tap + 1'b1;
                      tap_load <= 1'b1;
                      timer    <= 0;
                      scan_ph  <= 2'd0;
                    end
                  end
            default: scan_ph <= 2'd0;
          endcase
        end

        S_SFIND: begin
          if (j <= 6'd31 && map_d[j[4:0]]) begin
            if (cur_len == 0) cur_start <= j[4:0];
            cur_len <= cur_len + 1'b1;
            j       <= j + 1'b1;
          end else begin
            if (cur_len > best_len) begin
              best_len <= cur_len;
              best_tap <= cur_start + cur_len[5:1];         // centre of run
            end
            cur_len <= 0;
            if (j == 6'd32) begin j <= 0; seq <= S_SPRNT; end
            else            j <= j + 1'b1;
          end
        end

        S_SPRNT: begin
          if (!tx_busy && !tx_send) begin
            if (j <= 6'd31) begin
              tx_data <= map_d[j[4:0]] ? 8'h23 : 8'h2E;     // '#' / '.'
              tx_send <= 1'b1; j <= j + 1'b1;
            end else if (j == 6'd32) begin
              tx_data <= 8'h20; tx_send <= 1'b1; j <= j + 1'b1;
            end else if (j == 6'd33) begin
              tx_data <= hexchr({3'b000, best_tap[4]}); tx_send <= 1'b1; j <= j + 1'b1;
            end else if (j == 6'd34) begin
              tx_data <= hexchr(best_tap[3:0]); tx_send <= 1'b1; j <= j + 1'b1;
            end else if (j == 6'd35) begin
              tx_data <= 8'h0D; tx_send <= 1'b1; j <= j + 1'b1;
            end else begin
              tx_data  <= 8'h0A; tx_send <= 1'b1;
              dat_tap  <= best_tap; fclk_tap <= best_tap; tap_load <= 1'b1;
              seq      <= S_IDLE;
            end
          end
        end

        //==================== deep capture (binary) ========================
        S_DCAP: begin
          if (deep_done) begin
            deep_addr <= 0; dlat <= 1'b0; seq <= S_DRD;
          end else if (timer == 32'd10_000_000) begin
            timer <= 0; echo_ch <= 8'h3F; seq <= S_ECHO1;
          end else timer <= timer + 1'b1;
        end

        S_DRD: begin                                        // BRAM read latency
          dlat <= 1'b1;
          if (dlat) seq <= S_DLO;
        end

        S_DLO: if (!tx_busy && !tx_send) begin
                 tx_data <= deep_data[7:0];                 // little-endian
                 tx_send <= 1'b1;
                 seq     <= S_DHI;
               end

        S_DHI: if (!tx_busy && !tx_send) begin
                 tx_data <= deep_data[15:8];
                 tx_send <= 1'b1;
                 if (deep_addr == 13'd8191) seq <= S_IDLE;
                 else begin
                   deep_addr <= deep_addr + 1'b1;
                   dlat      <= 1'b0;
                   seq       <= S_DRD;
                 end
               end

        //==================== echo ========================================
        S_ECHO1: if (!tx_busy) begin
                   tx_data <= echo_ch; tx_send <= 1'b1; seq <= S_ECHO2; end
        S_ECHO2: if (!tx_busy && !tx_send) begin
                   tx_data <= 8'h0D;   tx_send <= 1'b1; seq <= S_ECHO3; end
        S_ECHO3: if (!tx_busy && !tx_send) begin
                   tx_data <= 8'h0A;   tx_send <= 1'b1; seq <= S_IDLE;  end

        default: seq <= S_IDLE;
      endcase
    end
  end

endmodule