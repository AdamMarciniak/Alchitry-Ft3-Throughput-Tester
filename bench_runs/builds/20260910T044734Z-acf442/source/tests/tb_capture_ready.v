`timescale 1ns/1ps
// Production controller + pulser, with a 40 MSPS ADC FIFO model and deliberate
// downstream stalls longer than one nominal shot. No vendor simulation models.
module tb_capture_ready;
    reg clk=0, rst=1, ctrl_empty=1, tx_full=0;
    reg [31:0] ctrl_word=0;
    wire [31:0] tx_data;
    wire tx_valid, adc_read, ready, arm, sync, fault, mux_clk, ina, inb, oe;
    wire [5:0] elem;
    wire [23:0] rx_time;
    reg adc_tog=0;
    integer cyc=0, div=0, grid=0, head=0, tail=0, count=0, sequence=0;
    reg [31:0] memory [0:4095];
    wire adc_empty=(count==0);
    wire [31:0] adc_word=memory[head];
    integer shots=0, packets=0, words=0, last_data=0, previous_shot=-1;
    integer first_period=0, stalled_period=0, stall_started=0;
    integer gate_at=-1, sync_at=-1, rx_end_at=-1;
    reg previous_rx=0;
    reg pop_now;
    always #5 clk=~clk;

    ctrl_decode ctrl(.clk(clk),.rst(rst),.ctrl_word(ctrl_word),.ctrl_empty(ctrl_empty),
        .tx_full(tx_full),.tx_wr_rst_busy(1'b0),.tx_din(tx_data),.tx_wr_en(tx_valid),
        .adc_word(adc_word),.adc_empty(adc_empty),.adc_rd_en(adc_read),
        .tx_sync(sync),.tx_elem(elem),.capture_ready(ready),.pls_arm(arm),.pls_t_rx(rx_time));
    tx_sequencer #(.T_OE_WAIT(100),.CHAIN_CHECK(0)) pulser(
        .clk(clk),.rst(rst),.adc_sync_tog(adc_tog),.capture_ready(ready),
        .arm(arm),.start_frame(1'b0),.continuous(1'b1),.fault_clr(1'b0),
        .cfg_n_cycles(8'd2),.cfg_t_drive(16'd10),.cfg_t_dead(16'd4),
        .cfg_chirp_len(8'd0),.ch_wr(1'b0),.ch_wr_addr(8'd0),.ch_wr_data(16'd0),
        .cfg_t_settle(24'd500),.cfg_t_inhibit(24'd450),.cfg_t_ring(24'd300),
        .cfg_t_rx(rx_time),.el_wr(1'b0),.el_wr_addr(6'd0),.el_wr_data(6'd0),
        .cfg_list_len(7'd48),.tr_wr(1'b0),.tr_wr_addr(6'd0),.tr_wr_data(12'd0),
        .mux_dout(1'b0),.mux_clk(mux_clk),.pulse_ina(ina),.pulse_inb(inb),.pulse_oe(oe),
        .tx_sync(sync),.element_current(elem),.fault(fault));

    // Consume the old FWFT head on the same edge as the production controller.
    // Produce one packed word every 5 clocks, monotonically tagged for checking.
    always @(posedge clk) begin
        cyc=cyc+1;
        pop_now=adc_read && !adc_empty;
        if (!rst) begin
            if (sync) begin
                if (ctrl.sstate!==3'd1 || !ready) $fatal(1,"Shot while capture unavailable");
                if (elem !== (shots%48)) $fatal(1,"Skipped/reordered physical element");
                if (previous_shot>=0) begin
                    if (shots==1) first_period=cyc-previous_shot;
                    if (shots==2) stalled_period=cyc-previous_shot;
                end
                if (rx_end_at>=0 && cyc-rx_end_at<5000) $fatal(1,"DAC gap shortened");
                previous_shot=cyc;sync_at=cyc;shots=shots+1;
            end
            if (ctrl.sstate==3'd4 && !previous_rx) begin
                gate_at=cyc;
                if (gate_at-sync_at !=1602) $fatal(1,"Receive origin changed with backpressure: %0d",gate_at-sync_at);
            end
            previous_rx=(ctrl.sstate==3'd4);
            if ((ctrl.sstate==3'd2 || ctrl.sstate==3'd4) && mux_clk)
                $fatal(1,"MUX clocks during capture");
            if (fault) $fatal(1,"Unexpected pulser fault");
            if (ina && !inb) $fatal(1,"Shoot-through combination");
            if (tx_valid) begin
                if (tx_data[31:22]==10'h384) begin
                    if (words!=0) $fatal(1,"Torn frame");
                    if (tx_data[21:16] !== (packets%48)) $fatal(1,"Wrong packet element");
                    if (tx_data[15:0] !== packets) $fatal(1,"Wrong packet counter");
                    words=3208;
                    last_data=-1;
                end else begin
                    if (words==0) $fatal(1,"Data without header");
                    if (last_data>=0 && tx_data!=last_data+1) $fatal(1,"Noncontiguous RF payload");
                    last_data=tx_data;
                    words=words-1;
                    if (words==0) begin packets=packets+1;rx_end_at=cyc;end
                end
            end
        end
        // Delay model updates until all DUT blocks have sampled the old FIFO.
        #1;
        if (rst) begin head=0;tail=0;count=0;sequence=0;div=0;grid=0;end
        else begin
            if (pop_now) begin head=(head+1)%4096;count=count-1;end
            if (div==4) begin
                div=0;
                if (count<4096) begin memory[tail]=sequence;tail=(tail+1)%4096;count=count+1;end
                sequence=sequence+1;
            end else div=div+1;
            if (grid==19) begin adc_tog=~adc_tog;grid=0;end else grid=grid+1;
        end
    end
    task command(input [31:0] value);
        begin @(negedge clk);ctrl_word=value;ctrl_empty=0;
              @(negedge clk);ctrl_empty=1;end
    endtask
    initial begin
        repeat(4) @(negedge clk);rst=0;
        command(32'h0b000c88); // 3208 packed words, ~12 cm plus receive offset
        command(32'h0c000640); // 16 us
        command(32'h0e001388); // 50 us DAC recovery gap
        command(32'h17005c58); // 236.40 us conservative host RX budget
        command(32'h07000002);command(32'h01000000);command(32'h10000001);
        wait(shots==2);@(negedge clk);tx_full=1;stall_started=cyc;
        repeat(50000) @(negedge clk); // 500 us: exceeds nominal period and FIFO slack
        if (shots!=2) $fatal(1,"Pulser advanced during stalled receive");
        tx_full=0;
        wait(packets==49);
        if (stalled_period<=first_period+20000) $fatal(1,"Stall did not stretch shot interval");
        wait(shots==50);@(negedge clk);tx_full=1;
        repeat(30000) @(negedge clk);
        if (shots!=50) $fatal(1,"New shot during second stall");
        command(32'h10000000);
        repeat(5) @(negedge clk);
        if (oe || ina || !inb) $fatal(1,"Disarm did not park outputs");
        tx_full=0;repeat(1000) @(negedge clk);
        if (shots!=50) $fatal(1,"Stall release rearmed pulser");
        $display("CAPTURE_READY_TEST_PASS shots=%0d packets=%0d normal_cycles=%0d stalled_cycles=%0d",shots,packets,first_period,stalled_period);
        $finish;
    end
    initial begin #30000000;$fatal(1,"Test timed out");end
endmodule
