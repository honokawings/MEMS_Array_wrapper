# 麦克风阵列FPGA驱动spec

> 当前阶段：按后续目标，已将下述前处理规格扩展为 PG2L200H 上的完整采集和千兆 UDP 发送系统。早期“不考虑传输”描述保留为原始需求记录，当前实现入口见文末“完整系统”。

## 设计要求
1. 128阵元螺旋麦克风阵列，MEMS麦克风型号为IM72D128V01
2. 使用FPGA对128路麦克风数据进行前处理，后续的数据能够发送到上位机通过SRP-PHAT算法进行声源定位，目前只需要实现前处理算法的部分不需要考虑传输
3. 不损失麦克风本身约 72 dB(A) 的 SNR、128 路严格同步、通道间相位关系不被破坏、后续算法拿到足够高精度且可校准的数据
4. 严格按照我已经规划好的目录结构进行组织，如果有需要可以增加子目录，后续也要进行整洁的文件组织

## 设计步骤
1. 先实现前处理链设计，尽可能发挥MEMS麦克风的性能，并冻结算法规格
2. 对算法建立浮点 Golden Model，用 Python 实现理想模型，并输出性能仿真报告
3. 对算法做定点化设计，并确保性能几乎不损失，并建立Cmodel模型算法rm
4. 进行RTL微架构设计，确定多通道硬件并行度和适当的通道调度策略
5. 进行RTL实现，完善设计细节，RTL设计要确保可综合并尽快提高可读性，模块划分要清晰解耦
6. 建立UT验证环境，确保RTL设计和定点化算法rm规格功能一致

## MEMS麦克风引脚映射
### CLK
CLK0～CLK7：八个独立输出引脚，共用同一 3.072 MHz 分频源、相位和复位。物理负载按阵列接线分组，DATA0～63 的逻辑通道编号不变。

MEMS VDD=1.8 V。八路时钟采用 LVCMOS18、16 mA、FAST；Bank L6/L7 必须由硬件设置为 1.8 V。当前映射为 J10/L6 的 CLK0～7、J26/L7 的 DATA0～31、J25/L6 的 DATA32～63，麦克风接口不再占用 L5。详见[八路时钟与电压核查](doc/reports/clk8_18v_update.md)。

### J10-40pin
GND           |   A5V0
R21 -         |   R20 -
N19 -         |   P19 -
M25 -         |   M24 -
T25 -         |   T24 -
R22 -         |   T22 -
K26 -         |   K25 -
L25 -         |   L24 -
L23 -         |   L22 -
AA25-CLK7     |   Y25 -CLK6
AB25-CLK4     |   AA24-CLK3
AC24-         |   AB24-
R23 -         |   T23 -
P26 -         |   R26 -
M26 -         |   N26 -
M22 -         |   M21 -
U26 -CLK5     |   U25 -CLK2
AC26-CLK0     |   AB26-CLK1
GND           |   GND
A3V3          |   A3V3

### J25-40pin
GND           |   A5V0
V14 -DATA34   |   U14 -DATA38
T18 -DATA33   |   T17 -DATA36
W18 -DATA37   |   V18 -DATA39
U19 -DATA35   |   T19 -DATA60
U20 -DATA46   |   T20 -DATA58
W26 -DATA42   |   V26 -DATA63
Y26 -DATA47   |   W25 -DATA61
Y23 -DATA44   |   Y22 -DATA62
W23 -DATA45   |   V23 -DATA57
Y20 -DATA41   |   W20 -DATA59
W19 -DATA43   |   V19 -DATA53
T15 -DATA40   |   T14 -DATA54
U16 -DATA32   |   U15 -DATA55
V17 -DATA56   |   V16 -DATA51
V21 -DATA48   |   U21 -DATA52
W24 -DATA50   |   V24 -DATA49
AA23-         |   AA22-
GND           |   GND
A3V3          |   A3V3

### J26-40pin
GND           |   A5V0
AC23-DATA2    |   AC22-DATA1
AD26-DATA3    |   AD25-DATA0
AD24-DATA4    |   AD23-DATA16
AF20-DATA10   |   AF19-DATA24
AE20-DATA5    |   AD20-DATA8
AF18-DATA7    |   AE18-DATA25
AF17-DATA6    |   AE17-DATA28
AB20-DATA12   |   AA20-DATA26
AD17-DATA15   |   AC17-DATA9
AC16-DATA14   |   AB16-DATA30
W15 -DATA13   |   W14 -DATA29
AE26-DATA11   |   AE25-DATA27
AF25-DATA22   |   AF24-DATA31
AF23-DATA19   |   AE23-DATA17
AD19-DATA21   |   AC19-DATA18
AE21-DATA23   |   AD21-DATA20
AF22-         |   AE22-
GND           |   GND
A3V3          |   A3V3

## 千兆网口接口映射
使用Realtek RTL8211F-CG PHY实现了一个10/100/1000以太网端口，用于网络连接
| 信号名称 | 描述 | FPGA 管脚 | RTL8211F Pin |
|---|---|---|---|
| PHY0_RXC | 接收时钟线 | D19 | 27 |
| PHY0_RXCTRL | 接收控制线 | H16 | 26 |
| PHY0_RXD[3] | 接收数据线 3 | B19 | 22 |
| PHY0_RXD[2] | 接收数据线 2 | A19 | 23 |
| PHY0_RXD[1] | 接收数据线 1 | E16 | 24 |
| PHY0_RXD[0] | 接收数据线 0 | D16 | 25 |
| PHY0_TXC | 发送时钟线 | G16 | 20 |
| PHY0_TXCTRL | 发送控制线 | D20 | 19 |
| PHY0_TXD[3] | 发送数据线 3 | D21 | 15 |
| PHY0_TXD[2] | 发送数据线 2 | C21 | 16 |
| PHY0_TXD[1] | 发送数据线 1 | B21 | 17 |
| PHY0_TXD[0] | 发送数据线 0 | E20 | 18 |
| PHY0_MDC | 控制总线时钟 | A25 | 13 |
| PHY0_MDIO | 控制总线数据 | E21 | 14 |
| RSTN_OUT | 复位控制线，低有效 | G25 | 12 |

## 已实现的 v1.0

根据后续确认采用 **64 根共享 PDM DATA、128 路麦克风**，先提供不绑定具体 FPGA 的 RTL。声源定位有效通带为 **20 Hz～16 kHz**，输出 **48 kHz / 24 位有符号 PCM**，要求输入系统时钟为 **122.88 MHz**。

前处理链：双相采集 → CIC5 /8 → FIR63 补偿 /4 → FIR127 抗混叠 /2 → 增益/偏置校准 → 带帧号与通道号的 PCM 输出。包含 Python 浮点与定点模型、C++ 逐位参考模型、冻结系数、性能报告以及 ModelSim 自检回归。v1.0 阶段未包含上位机传输；当前完整系统已增加传输，SRP-PHAT 定位算法仍由上位机处理。

| 内容 | 入口 |
|---|---|
| 冻结算法、定点格式和时间轴 | [doc/algorithm_spec.md](doc/algorithm_spec.md) |
| RTL 模块和多通道调度 | [doc/rtl_architecture.md](doc/rtl_architecture.md) |
| 运行方法、接口与校准步骤 | [doc/integration.md](doc/integration.md) |
| 实际性能仿真及图表 | [doc/reports/performance.md](doc/reports/performance.md) |
| 功能验证结果 | [doc/reports/verification.md](doc/reports/verification.md) |
| 顶层 RTL | [rtl/mems_array_top.sv](rtl/mems_array_top.sv) |
| Python 模型 / Cmodel | [lib/model](lib/model) / [lib/cmodel/mems_rm.cpp](lib/cmodel/mems_rm.cpp) |
| 前处理回归（v1.0） | [sim/sim.bat](sim/sim.bat) |

在工程根目录执行 `.\sim\sim.bat`。具体依赖、其他运行方式和生成文件位置见集成指南。保留既有 `doc / lib / log / rtl / sim / tb` 六个顶层目录；新增内容均放在相应目录内。

v1.0 的验证范围为数字算法与 RTL 功能；当前具体器件上的实现见下方“完整系统”。数字验证不等同于实测声学 SNR，定位仍需要实际阵元坐标及声学校准数据。

## 完整系统

**当前八路同源时钟、1.8 V 完整系统（2026-09-20）**：已按最新版引脚表实现 J10/L6 的 CLK0～7、J26/L7 的 DATA0～31、J25/L6 的 DATA32～63。八路 CLK 为同源 3.072 MHz、LVCMOS18、16 mA、FAST。推荐[下载位流](fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/generate_bitstream/mems_array_pg2l200h.sbit)，[最终发布检查](fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/release.json)为 PASS，12 项功能回归及 146 项检查器测试通过，双角时序无违例。新位流尚未上板；下载接入前须将实际 L6/L7 VCCIO 设为并实测确认 1.8 V。详见[引脚、时序和交付报告](doc/reports/clk8_18v_update.md)。

**此前四路时钟 UART 完整系统（2026-09-19 修正版；不适用于当前 1.8 V 阵列直连）**：已修正以太网 PLL 参数，并通过 COM3 反馈 PHY/MDIO、ARP、UDP、PCM 与时钟状态。本次进一步修正“等待 ARP 时采集队列溢出”：ARP 就绪后才启动采集，模式切换保留对端地址。正式版 `fpga/build/MEMS_Array_uart_arp_ready_routed/` 已通过 [发布检查](fpga/build/MEMS_Array_uart_arp_ready_routed/release.json)、12 项功能回归及 116 项检查器测试，双角时序无违例，音频慢角 setup 裕量 +0.118 ns。[下载位流](fpga/build/MEMS_Array_uart_arp_ready_routed/generate_bitstream/mems_array_pg2l200h.sbit) 已 JTAG 下载并实测：PHY/MDIO → ARP → UDP 通过，两级 BIST PASS，157,314,048 个通道样本逐位一致，启动/模式切换缺帧与 FPGA 溢出均为 0。恢复真实输入后发现 128 路均为正满量程，阵列接入/供电与 PDM 接线仍待核对，不能将数字自检通过等同于真实声学验收。详见 [本轮修正与实测报告](doc/reports/arp_ready_fix.md) 和 [UART 联调指南](doc/system_uart_debug.md)。旧版问题证据保留在 [先前实板报告](doc/reports/uart_board_test_20260919.md)。

此前五键五灯映射已实测通过；旧时钟诊断确认以太网 PLL 未锁定并阻止系统复位释放，参数存在 PFD/带宽组合约束问题。将 PFD 从 125 MHz 改为 31.25 MHz、保持输出频率不变后，[COM3 UART 时钟诊断](fpga/diagnostics/uart_clock/README.md) 已通过 30 秒实板测试：125 条完整记录，三个 PLL 锁定、四路频率合格、复位释放；软件复位恢复、自检模式开关及心跳检查通过，无丢帧或串口接收错误。见 [实测摘要](log/clock_uart/board_verified_20260918_223923/summary.json)。该独立诊断将 PHY 保持复位，不提供网络收发；其通过不能代替新版完整系统网络验收。

**2026-09-17 新增按键自测**：KEY1 切换内部 PDM 自测，LED0～4 显示心跳、模式、数值校验、发送和故障；未连接麦克风阵列时仍可测试完整前处理与千兆通信。11 项全量回归已通过，专项自测的 15,360 个线上 PCM 样本逐位一致。使用方法见 [自测指南](doc/selftest.md)，上位机开发交付文档见 [接口开发参考](doc/host_protocol_reference.md)，其中包含真实二进制报文样例。

历史自测构建 `fpga/build/MEMS_Array_selftest/` 的 [release.json](fpga/build/MEMS_Array_selftest/release.json) 及 [自测实现报告](doc/reports/selftest_implementation.md) 保留作当时实现证据。该位流包含后来实板发现的 PLL 参数问题，不作为本轮下载版本。2026-09-16 的 `fpga/build/MEMS_Array/` 及归档也保留旧版证据，旧位流没有按键自测功能。

目标器件为 **PG2L200H / FBB676 / -6**。板级连接依据本 README 的 J10、J25、J26、PHY0 映射及 `doc/盘古MINI系列开发板硬件指导手册_V1.3.pdf`。D18 的 27 MHz 经两级 PLL 产生准确的 122.88 MHz 音频时钟；N3/N2 的 125 MHz 差分参考经 PLL 倍频至 250 MHz，再由专用单沿分频器生成 125 MHz 网口时钟，以改善占空比。复位为 C22 的低有效 KEY0。

数据路径为 **64 根共享 PDM 线 → 128 通道同步前处理与校准 → 跨时钟 FIFO → 3 帧打包 → UDP/IPv4/ARP MAC → RGMII → RTL8211F-CG**。当前 RTL 已扩展为八路同源 3.072 MHz 麦克风时钟，新版引脚、1.8 V 约束和推荐位流均已完成并通过发布检查。输出保持 48 kHz / 24 位，单包 1208 字节，线路占用约 163.072 Mbit/s。

| 内容 | 入口 |
|---|---|
| 完整系统 UART 状态、命令与逐级网络验收 | [doc/system_uart_debug.md](doc/system_uart_debug.md) |
| PLL 修正、UART 集成与本轮验证结果 | [doc/reports/uart_system_implementation.md](doc/reports/uart_system_implementation.md) |
| 无麦克风自测、按键和 LED | [doc/selftest.md](doc/selftest.md) |
| 上位机软件开发参考（含真实报文） | [doc/host_protocol_reference.md](doc/host_protocol_reference.md) |
| 可交付给上位机开发人员的参考包 | [M128_Host_Reference_v1.1.zip](doc/deliverables/M128_Host_Reference_v1.1.zip) |
| 自测捕获数据逐样本验收 | [lib/host/verify_selftest.py](lib/host/verify_selftest.py) |
| 板级完整顶层 | [rtl/board/mems_array_pg2l200h.sv](rtl/board/mems_array_pg2l200h.sv) |
| 可移植采集和网络内核 | [rtl/net/mems_ethernet_core.sv](rtl/net/mems_ethernet_core.sv) |
| 数据包格式、帧号和会话定义 | [doc/transport_spec.md](doc/transport_spec.md) |
| PHY 管理、数据打包及 Ethernet MAC | [rtl/net](rtl/net) |
| Pango 工程构建入口 | [fpga/scripts/build.py](fpga/scripts/build.py) |
| 位流发布检查 | [fpga/scripts/RELEASE_CHECK.md](fpga/scripts/RELEASE_CHECK.md) |
| 烧录、接线与首次采集 | [doc/board_bringup.md](doc/board_bringup.md) |
| 板级引脚与时序约束 | [fpga/constraints](fpga/constraints) |
| 前处理、网络、端到端与厂商原语完整回归 | [sim/verify_all.py](sim/verify_all.py) |
| 完整系统验证报告 | [doc/reports/system_verification.md](doc/reports/system_verification.md) |
| PDM 到线上 UDP 的逐位核对 | [tb/net/tb_mems_ethernet_core.sv](tb/net/tb_mems_ethernet_core.sv) |
| 上位机接收、原始数据保存与缺帧检测 | [lib/host/receive_pcm.py](lib/host/receive_pcm.py) / [doc/host_capture.md](doc/host_capture.md) |

运行 `python sim/verify_all.py` 完成所有层次回归；`--rtl-only` 复用已生成参考向量。原 `sim/sim.bat` 仍保留为前处理回归入口。软件依赖见集成指南，厂商原语仿真另需已安装的 Pango Design Suite。

默认 FPGA 地址为 `192.168.10.2`，接收电脑地址为 `192.168.10.1`，UDP 端口 `5000`，只支持同一二层网段。PHY 自动初始化并配置 1000M 全双工、RGMII 内部延迟和关闭 EEE 广告。物理链路建立后主动解析 ARP，对端地址有效且校准就绪后才开始采集；模式切换保留 ARP 缓存，物理断线重连会清除缓存、改变会话号并重新解析。

默认校准系数为增益 1、偏置 0。实测校准的两列整数文件可用 `python lib/model/export_board_calibration.py measured.txt` 写入板级校准 ROM，再重新构建位流。不得把测试向量中的故意饱和/异常校准值用于真实阵列。

MEMS 供电为 1.8 V，不能继续沿用旧位流的 3.3 V 时钟输出。当前 64 根 DATA 和八路 CLK 均位于可调电压 L6/L7，全部使用 LVCMOS18。按开发板手册将 J24 选择为 VADJ=1.8 V，J20 选择 VADJ 为 L6/L7 供电；接入阵列前须测量实际电压。约束不会改变板上供电，扩展口 A3V3/A5V0 电源针也不会变成 1.8 V。125 MHz 差分参考仍为 1.5 V SSTL15D_I；PHY、UART、按键和 LED 保持各自原有电平。

接口时序包含明确的板级假设：RGMII 发送端要求 FPGA 引脚处 TXD/TXCTRL 相对 TXC 的偏差不超过 ±0.3 ns，另预留 PCB 相对走线偏差 ±0.2 ns。PDM 的 20 ns 外部传播预算包含时钟扇出/缓冲、连接器及往返布线；八路均分时每路 CLK 对应 16 只麦克风（实际以阵列接线为准），不能仅凭 FPGA 内部输出路径通过时序检查就认定该扇出已经验证。IM72D128V01 手册未给出 CLK 输入电容，要求麦克风引脚处时钟上升/下降时间不超过 13 ns，3.072 MHz 下占空比为 48%～52%；其 DATA 有效延迟 100 ns 的测试负载为 100 pF/100 kΩ。实际阵列须通过外部时钟缓冲方案或带真实负载的测量保证这些边界；现有资料不足以证明八个 FPGA 引脚的实际带载波形满足上述要求。
