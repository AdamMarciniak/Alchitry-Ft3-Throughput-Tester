# Transmit/receive options for improving weak-echo imaging

**Two adjacent elements transmitting together, followed by one-element receive, is feasible in principle on this topology.** It is not available in the current sequencer, and it is not a guaranteed SNR improvement. The shared pulser makes both elements use the same waveform and phase; the extra electrical load and angular interference matter.

This assessment follows the [three heart clip comparison](heart-preset-comparison-2026-09-09.md). That comparison found no clipping, a gain-dependent noise increase, varying echo strengths and no consistent tissue-image improvement. More display gain has not resolved the limitation. Probe movement and acoustic shadowing remain confounders, alongside the 26.64 ms sequential aperture.

## What the hardware actually permits

MAX14866 contains independent SPST switches, so its hardware can connect more than one selected channel. The board's tied leaf COM pins and common pulser mean selecting two leaf elements places them electrically in parallel. The current FPGA's `word_ok` checks intentionally require one root and one leaf switch. The code's comment that two connected elements are damaging describes the existing design constraint; the switch architecture itself does not establish that any intentional multi-element load must be destructive. A new mode needs explicit limits and load measurements, not removal of the checks. [ADI MAX14866 product documentation](https://www.analog.com/en/products/max14866.html).

For the first pair experiment, use **zero-based elements 20 and 21 transmitting, then element 20 receiving**. Both are adjacent, near the aperture center and on the same leaf bank in the actual `mux_code()` table. They are outside both the earlier water exclusion list and the current [25,46] exclusion. Their health must still be checked on the bench.

The offline planner reads the actual RTL table and gives these design masks:

| Phase | Physical selection | 64-bit chain word, BR3/BR2/BR1/ROOT |
|---|---|---|
| Transmit | 20 + 21 | `0300000000000800` |
| Receive | 20 | `0200000000000800` |

These are design data, **not commands for the current firmware**. The current firmware rejects the pair mask. Initially keep the pair in one leaf bank and make RX a member of TX, so the transition only removes one parallel element. Cross-bank groups add another connected bank's parasitics and should be a later experiment.

Both elements draw current from the same pulser. Approximately, an added capacitance requires extra current `I = C * dV/dt`. If the output edge slows or its voltage falls, the ideal acoustic gain below will not be achieved. The actual probe/mux load has not been measured sufficiently to predict this. Returning the drive inputs to idle does not prove the analog bus has reached ground; check the waveform and recovery directly.

## Two-element gain has a field-of-view cost

For equal-voltage point elements with pitch 0.3375 mm, the far-field pressure factor is

`A(theta) = |sum_j exp(-i * 2*pi*f/c * x_j * sin(theta))|`.

At 3.5 MHz and c=1540 m/s, the ideal two-element result relative to one element is:

| Angle from the pair normal | Ideal pressure gain |
|---|---:|
| 0 degrees | +6.02 dB |
| 10 degrees | +5.24 dB |
| 20 degrees | +2.66 dB |
| 30 degrees | -2.91 dB |

Thus an in-phase pair can strengthen the center while reducing the edge of the current approximately +/-30-degree acceptance region. At higher frequencies cancellation approaches the sector edge sooner. Four elements give an ideal +12 dB on-axis pressure but a narrower central beam and additional lobes/nulls. More elements are not automatically better for a wide cardiac sector.

These are ideal array-factor calculations, **not measured SNR gains**. They omit electrical loading, individual element directivity, near-field behavior, tissue attenuation and coupling. The +6 dB potential also assumes unchanged receive noise and preserved per-element voltage. Total transmitted energy increases; this is not free sensitivity at fixed acoustic output.

## A transmit-to-receive switch needs its own timing

The current sequencer keeps the same MUX selection throughout receive and deliberately stops chain clocking during that window. A straightforward TX-pair/RX-single mode needs an explicit transition before any RF marked as valid:

1. Select the two TX elements; latch; settle; emit the burst.
2. Return to driver idle and allow the HV-programming inhibit interval to expire.
3. Shift the single-RX mask, latch it and wait for switch/analog recovery.
4. Capture RF with the RX path stable and all MUX clocks quiet.

MAX14866 may ignore programming for up to 4.5 microseconds following detection of an HV signal; its switch changes also take microseconds. The current implementation uses a 10 MHz, 64-bit chain, so one shift takes 6.4 microseconds. [ADI MAX14866 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX14866.pdf).

For the current 1.04 microsecond burst, budgeting 4.5 microseconds inhibit, 6.4 microseconds shift, 0.07 microseconds latch guards and the current 5 microsecond settle gives **17.01 microseconds**, before extra FSM and analog margins. The present 16 microsecond receive start is too early for that straightforward implementation.

**A better proposal preloads the RX word before firing.** The MAX14866 shift register and output latch are separate: LE high holds the selected switches while new serial data is shifted in. Therefore the sequence can be:

1. Shift/latch the TX-pair word.
2. Keep LE high and preload the single-RX word; the TX pair stays selected.
3. Let digital/analog activity settle, then fire the TX pair.
4. Wait for HV inhibition to expire, pulse LE to select RX, then allow switch/analog recovery.
5. Begin capture with no MUX serial clocks during receive.

This removes the serial transfer from the post-transmit budget: **1.04 + 4.5 + 0.07 + 5 = 10.61 microseconds**, leaving about5.39 microseconds before the current16 microsecond receive start for additional FSM/analog margin. It adds pre-transmit work and does not eliminate switch charge injection. It is a feasible timing proposal based on the latch behavior, not a measured recovery result. Chain-word tracking and any DOUT check must distinguish the latched TX word from the preloaded RX word.

For an implementation that instead shifts RX after transmit,24 microseconds is a proposed conservative starting receive offset (about18.5 mm equivalent range at1540 m/s). It is not a validated recovery time. Longer bursts need either budget recalculated. The inhibit interval starts after the last relevant analog excursion, not merely a software timestamp.

Keep the existing shoot-through interlock, dead-time floor, watchdog and lease behavior. The new mode must validate a bounded TX pair and exactly one RX; disarm/fault/lease expiry must leave the output inactive and switches open. Mid-frame mode/list updates need to be rejected or deferred to a stopped state.

## Reconstruction must know the transmit pattern

The current host assumes the same element transmits and receives and samples a round-trip path `2 * distance / c`. With separate TX and RX, the path is instead

`time = (distance(TX,pixel) + distance(pixel,RX)) / c`.

With two simultaneous transmitters, the receive trace contains the **sum of two transmit wavefields**. That sum cannot be treated as two independently measured channels, nor reproduced from the existing monostatic RF by duplicating rows. Near the central beam, a virtual transmitter at the pair center is an approximation; a robust broad-band reconstruction must account for the pair's phase, directivity and delayed waveform sum.

The first bench comparison should assess the wire echo in raw RF and a restricted central ROI. A wider image requires the changed forward model. Save TX element list/mask, RX element, shot ordinal, waveform, reference timing and exact shot schedule with every capture. Existing packet headers identify a single element, and the host/portable RF format assumes 48 rows: an experimental shot list needs explicit protocol/metadata support rather than relabeling pair data as ordinary 48-element RF.

## Options worth comparing

| Option | Potential benefit | Main cost / restriction | Priority |
|---|---|---|---|
| Longer chirp with pulse compression | More echo energy at the same peak voltage; 4x energy gives an ideal +6 dB matched-filter SNR benefit in white noise | More acoustic energy, blind range and potential range sidelobes; actual probe response and attenuation matter | First low-rewiring SNR experiment |
| Two adjacent TX, one RX | Ideal +6 dB So central pressure if voltage is maintained; single receiver after transmit | Added load, narrower useful field, RX switching and different reconstruction | First new MUX-mode experiment |
| One TX, a different RX | Distinguishes same-element recovery from acoustic/circuit clutter; enables off-diagonal synthetic-aperture data | No inherent transmit-energy gain; shared root/AFE still sees the transmit event | Useful diagnostic mode |
| Shorter sequential aperture | Less opportunity for motion to corrupt coherent focusing | Timing, settling and throughput must still pass; reducing element count reduces aperture/sampling | High priority for moving targets |
| Adjacent repeated shots, then averaging | 2 repeats: ideal +3 dB; 4 repeats: ideal +6 dB for independent noise | More time and energy; motion and correlated clutter spoil averaging | Static bench first |
| Parallel independent receive channels | Receive more spatial information from each firing; reduce repeated firings | New analog routing/protection and FPGA LVDS lanes | Stronger architectural upgrade |

The current chirp is already enabled but lasts only about 1 microsecond. A measured **2–4 microsecond chirp** with correctly normalized matched or sidelobe-controlled compression is a more meaningful new experiment than re-enabling the existing matched-filter checkbox on the same short recording. Use a measured wire echo/transfer response to validate decoding; the digital drive reference alone omits the probe and analog path. The exact ideal gain depends on transmitted energy and noise, not the mere presence of a chirp. [Primary study: coded excitation for synthetic aperture imaging](https://pubmed.ncbi.nlm.nih.gov/15801306/).

Shortening a 48-shot aperture from26.64 ms toward roughly13 ms could matter even without a raw per-shot SNR increase. A 24-shot list at the same period is nominally13.32 ms, but that changes spatial sampling/aperture. The host's current dead-element mask only omits rows in reconstruction and does not shorten physical acquisition. Its element-count control takes the first elements, not automatically a centered subset. A proper centered/sparse schedule must be explicit. Full48x48 acquisition through one ADC would take approximately **1.28 seconds** at the present shot period, so exhaustive full-matrix acquisition is a poor moving-heart starting point.

Hadamard/Golay combinations and pulse inversion are later options, not automatic fixes. This one pulser cannot supply independent simultaneous element polarities or focusing delays. Sequential codes require extra shots and can suffer motion mismatch. Pulse inversion also removes much of the strong linear response, which is undesirable when the immediate problem is weak fundamental echoes.

## The larger hardware opportunity

The AFE5804 has **eight** receive channels. The schematic uses IN1 and OUT1; IN2–IN8 and OUT2–OUT8 are unconnected. Therefore extra channels cannot be enabled by a register or FPGA change alone. Additional input protection/AC coupling, LVDS routing, receive logic and a sample format are required. [TI AFE5804 documentation](https://www.ti.com/product/AFE5804).

A board-specific intermediate design could put one independent receive path on each of the three leaf-bank common nodes. Root switches would connect the pulser for transmit and isolate those banks for receive; one selected element per bank could then be digitized simultaneously. This is a schematic-level proposal requiring isolation and loading analysis, additional protected AFE inputs and lane routing. It is not achieved by closing three switches onto the existing common SMA/AFE input, which would merely combine them electrically and lose independent receive information.

Independent delayed pulsers and parallel receive channels are the route to a focused/diverging/steered transmit aperture. With one common pulser and tied buses, FPGA timing alone cannot produce arbitrary per-element simultaneous phase delays.

## Concrete next implementation boundary

Build a **bench-only explicit shot mode**, default off, supporting: `TX20/RX20`, `TX21/RX20`, and `TX[20,21]/RX20`. First compare electrical waveform, recovery, receiver noise and wire response. Then extend to a short validated list and its matching reconstruction. Preserve ordinary mode and reject the new data in an old host lacking its capability/version marker.

The offline planner is implemented in [tools/explore_transmit_modes.py](../tools/explore_transmit_modes.py); run `python tools/explore_transmit_modes.py`. It reads the actual element map, checks all48 single-element encode/decode mappings, validates the proposed same-bank pair, and writes timing/array-factor calculations to `bench_runs/transmit-options-20260909/model.json`. It imports no hardware-control code. This is a completed feasibility/planning tool, not implemented FPGA TX/RX switching firmware. The live sequencer and its protections remain unchanged by this exploration.

Any changed transmit pattern needs electrical and acoustic bench validation in water before on-body use, because grouping elements or lengthening excitation changes both load and output. The current heart RF cannot validate that new operating condition.
