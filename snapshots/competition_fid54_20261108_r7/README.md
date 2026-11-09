# Competition FPGA source snapshot for the independent sys project

This directory is a verified copy of the selected FID54 competition baseline, supplied for the same PG2L200H microphone-array hardware. The original competition directories and the repository master branch are not changed. It is a source handoff, not a new accepted FPGA image.

## Start here
1. Run: python snapshots/competition_fid54_20261108_r7/verify_snapshot.py
2. Read SOURCEPACK_PORTABLE.json for the 105 direct sources, include directories, constraints and parameters. Paths are relative to this directory.
3. Read SNAPSHOT_MANIFEST.json for every source SHA256 and active dependency closure.
4. PURE_FPGA_REUSE_CANDIDATES.json identifies 26 source/include files useful for a CPU-free audio transport top.

195 necessary files are included: 105 direct sources, 79 child sources from three native IDFs, five recursive includes, two firmware hex references and four constraints. Four INIT_FILE metadata strings were changed from local absolute paths to imem.hex or dmem.hex; their before/after hashes are explicit. No RTL logic was changed. All other copied source bytes are unchanged. Actual CPU memory initialization uses c_INIT_FILE=NONE and included init_param.v constants, both preserved. The omitted original build scripts contain machine-specific paths; create a fresh isolated PDS project instead.

## Build contract
- Pango Logos2 PG2L200H, FBB676, speed grade -6.
- Existing top: meeting_av_mini200. VIDEO_FRAME_PERIOD=8000000.
- Requires separately installed Pango PDS 2025.2, official GTP primitive libraries and a valid license. No executables, license keys or credentials are included.
- Native IDF source groups are complete. IP example, simulation and output groups are not the synthesis closure and are excluded. Vendor-generated IP remains vendor material; this handoff does not grant new IP rights.

## Audio and CPU-free extraction
27 MHz reference -> 96 MHz -> 122.88 MHz audio clock. PDM CLOCK_DIV=40 produces 3.072 MHz, using 64 DATA wires for 128 microphones. CIC5 /8 -> FIR63 /4 -> FIR127 /2 produces signed24 PCM at 48 kHz. FIR_LANES=8; eight physical microphone clock registers use the clockbank8 frontend.
Canonical mapping is raw^1, plus 32 for raw64..95 or minus32 for raw96..127. Complete frames emerge in canonical CH0..127 order.
The current competition top waits for RISC-V to set audio CONTROL 0x20006004 bit0 RUN. PHY initialization, ARP, UDP and the acquisition/filter datapath themselves are hardware.
The independent sys top may replace the RUN source with explicit hardware startup and remove the CPU, firmware memory, camera, DDR, spatial logic and video packet arbiter. A new top and independently validated clock/reset/CDC/constraint binding are still required. Preserve parity/calibration behavior rather than silently changing the acoustic transfer function.

## Ethernet and packet contract
The RTL8211F manager matches ID 0x001cc916, enables both internal 2 ns RGMII delays, disables EEE and advertises only gigabit full duplex. This implementation has no 10/100 fallback. GMII/RGMII clocks are 125 MHz; current pango_rgmii_io parameter TX_ASYNC_RESET=0.
MAC 02:00:00:00:01:28; FPGA 192.168.10.2; PC 192.168.10.1. Both UDP ports are 5001 in the current top, although ethernet_udp_engine defaults are 5000.
M128 v1 payload is 1208 bytes: 32-byte header plus 3 records of BE64 frame ID and 128 LE24 signed samples. Header fields are magic/version/header length/sample format/channels, BE32 sample rate 48000, BE16 frame count 3, BE16 record bytes 392, BE64 packet sequence, BE32 epoch and BE32 flags.
Raw PCM is 147.456 Mbit/s. Packet payload is 154.624 Mbit/s at 16000 packets/s; wire load including Ethernet/IP/UDP/preamble/FCS/IFG is approximately 163.072 Mbit/s. Require gigabit.
Raw transport does not backpressure capture. Drops and sticky overflow invalidate acoustic acceptance until restart; the PC must inspect frame IDs, packet sequence, epoch and flags.

## Known limits
Existing evidence establishes native compile/SYN, MAP and PNR completion for the selected full design. Full STA numeric coverage review was still pending. This source snapshot is not timing signoff, a bitstream, or hardware/acoustic acceptance.
Extract microphone, clock and Ethernet pin constraints, but rebind all hierarchy-specific clock/CDC queries. The full constraints also reference removed camera/DDR logic. Recheck the 125 MHz differential input discrepancy: RTL uses SSTL15D_I while the archived FDC uses HSTL15D_I with PAP_IO_NONE TRUE.
Historical DATA1 raw phases 2/3 correspond to canonical 3/2 and were reported stuck low. Current spatial processing masks canonical 2/3; raw acquisition keeps all 128 slots. Revalidate on hardware.
A verified complete 128-channel geometry/coordinate source is not included here and is still required for PC localization.
