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
CLK0: DATA 0-15
CLK1: DATA16-31
CLK2: DATA32-47
CLK3: DATA48-63

### J10-40pin
GND           |   A5V0
R21 -DATA2    |   R20 -DATA1
N19 -DATA3    |   P19 -DATA0
M25 -DATA4    |   M24 -DATA16
T25 -DATA10   |   T24 -DATA24
R22 -DATA5    |   T22 -DATA8
K26 -DATA7    |   K25 -DATA25
L25 -DATA6    |   L24 -DATA28
L23 -DATA12   |   L22 -DATA26
AA25-DATA15   |   Y25 -DATA9
AB25-DATA14   |   AA24-DATA30
AC24-DATA13   |   AB24-DATA29
R23 -DATA11   |   T23 -DATA27
P26 -DATA22   |   R26 -DATA31
M26 -DATA19   |   N26 -DATA17
M22 -DATA21   |   M21 -DATA18
U26 -DATA23   |   U25 -DATA20
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
AA23-CLK2     |   AA22-CLK3
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

**2026-09-16 工程发布已通过**：完整功能回归 10 项通过，PG2L200H 布局布线后的双角时序检查通过，已生成 [JTAG 位流 `.sbit`](fpga/build/MEMS_Array/generate_bitstream/mems_array_pg2l200h.sbit) 与 [原始配置 `.bin`](fpga/build/MEMS_Array/generate_bitstream/mems_array_pg2l200h.bin)。工程入口为 [MEMS_Array.pds](fpga/build/MEMS_Array/MEMS_Array.pds)，最终状态与校验值见 [release.json](fpga/build/MEMS_Array/release.json)，资源及时序见 [实现报告](doc/reports/fpga_implementation.md)。发布范围为工程上板联调：尚未实板测试，工具使用 `Pre-silicon` 模型，TXC 保守抖动敏感性检查仍为 `FAIL`；实际 TXC 与满载 PDM 时钟波形须按 [上板指南](doc/board_bringup.md) 测量确认。

目标器件为 **PG2L200H / FBB676 / -6**。板级连接依据本 README 的 J10、J25、PHY0 映射及 `doc/盘古MINI系列开发板硬件指导手册_V1.3.pdf`。D18 的 27 MHz 经两级 PLL 产生准确的 122.88 MHz 音频时钟；N3/N2 的 125 MHz 差分参考经 PLL 倍频至 250 MHz，再由专用单沿分频器生成 125 MHz 网口时钟，以改善占空比。复位为 C22 的低有效 KEY0。

数据路径为 **64 根共享 PDM 线 → 128 通道同步前处理与校准 → 跨时钟 FIFO → 3 帧打包 → UDP/IPv4/ARP MAC → RGMII → RTL8211F-CG**。四路麦克风时钟均为 3.072 MHz。输出保持 48 kHz / 24 位，单包 1208 字节，线路占用约 163.072 Mbit/s。

| 内容 | 入口 |
|---|---|
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

默认 FPGA 地址为 `192.168.10.2`，接收电脑地址为 `192.168.10.1`，UDP 端口 `5000`，只支持同一二层网段。PHY 自动初始化并配置 1000M 全双工、RGMII 内部延迟和关闭 EEE 广告。链路就绪后自动开始采集；断线重连会改变会话号并重新完成启动等待。

默认校准系数为增益 1、偏置 0。实测校准的两列整数文件可用 `python lib/model/export_board_calibration.py measured.txt` 写入板级校准 ROM，再重新构建位流。不得把测试向量中的故意饱和/异常校准值用于真实阵列。

引脚约束按麦克风接口 3.3 V 设置，使用前须按硬件手册核对可调 Bank L6/L7 的实际电压跳线；125 MHz 差分时钟所在 Bank 使用 1.5 V SSTL15D_I。板级仿真、实现报告和实际硬件测试是不同的验证范围，发布状态以最终构建与验证报告为准。

接口时序包含明确的板级假设：RGMII 发送端要求 FPGA 引脚处 TXD/TXCTRL 相对 TXC 的偏差不超过 ±0.3 ns，另预留 PCB 相对走线偏差 ±0.2 ns。PDM 的 20 ns 外部传播预算包含时钟扇出/缓冲、连接器及往返布线；每路 CLK 对应 32 只麦克风，不能仅凭 FPGA 内部输出路径通过时序检查就认定该扇出已经验证。IM72D128V01 手册未给出 CLK 输入电容，要求麦克风引脚处时钟上升/下降时间不超过 13 ns，3.072 MHz 下占空比为 48%～52%；其 DATA 有效延迟 100 ns 的测试负载为 100 pF/100 kΩ。实际阵列须通过外部时钟缓冲方案或带真实负载的测量保证这些边界；现有资料不足以证明四个 FPGA 引脚可以直接驱动全部麦克风。
