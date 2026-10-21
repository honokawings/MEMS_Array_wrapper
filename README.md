# 128 通道麦克风阵列 FPGA 驱动

面向盘古 MINI-200H（PG2L200H / FBB676 / -6），实现 64 根共享 PDM DATA 的同步采集、128 通道数字前处理、奇偶补偿、校准、千兆 UDP 发送及 PCM5102 I2S 监听。麦克风为 IM72D128V01；SRP-PHAT 声源定位由上位机实现。

## 当前交付状态

文档核对日期：2026-10-11。当前已发布并下载版本为 **`MEMS_Array_i2s_fir8_auto_20261011`**，包含启动直流估计、并行FIR舍入/饱和及8-lane共用乘加。其[18/18功能回归](log/i2s_parity/full_regression_fir8_auto_20261011.json)、唯一一轮原生路由、严格快/慢角时序与[发布门禁](fpga/build/MEMS_Array_i2s_fir8_auto_20261011/release.json)通过；16:19:06完成[JTAG SRAM下载](log/i2s_parity/jtag_fir8_auto_20261011/download.json)，未写Flash。**本次A–E数字验收通过，联合结果为PASS_WITH_KNOWN_ISSUES**，见[FIR8报告](doc/reports/i2s_fir8_auto_20261011.md)。

FIR8本次验证128/128监听通道、奇偶组独立零增益、PHY/MDIO→ARP→UDP及I2S BIST旁路，C+D共504,694,272个样本内容正确、连续无缺包；[联合验收](log/i2s_parity/fir8_auto_hardware_acceptance_20261011.json)绑定新位流和实际日志。退出BIST并恢复unity/I2S0后，[真实三秒采集](log/i2s_parity/fir8_auto_unity_spool_20261011/analysis.json)143,589帧、47,863包连续，但**DATA1（J26/AC22）通道2、3仍固定−8,388,608，ACRMS为0、rail占比100%**；仅这两路出现rail。此前捕获失败及[seed3历史结果](doc/reports/i2s_parity_dc_roundsat_seed3_20261011.md)保留。数字通过不等于供电、电气、声学或DAC模拟验收，full_goal_complete=false。

FIR8每级从16条乘加流水改为8条，轮流处理16组，128通道、48kHz及帧号不变；共同处理延迟增加1600个音频时钟，约13.02µs。六配置RAM定向11,435,616项和完整18层回归通过。[实际资源](log/i2s_parity/fir8_auto_map_actual_20261011.json)为APM132→68（−48.5%）、FF53,163→47,953、LUT33,190→28,512，分布式RAM2,290与DRM70.5不变。原路由入口Flow-0013证据已[归档](fpga/build/MEMS_Array_i2s_fir8_auto_20261011/resume_before_route)；从同一PLC恢复后只执行1轮，64819条连接全部布通。PNR用时1850秒，比seed3的8582秒减少78.4%；详细布线1528.25秒，比8360.84秒减少81.7%。这是两次实际构建的比较，不能仅归因于APM减少。

旧DC两轮setup−0.200/−0.369ns严格FAIL、未生成位流；roundsat seed2布线超时FAIL、最终时序未知，保留[历史记录](doc/reports/version_history.md)。用户允许setup≥−0.20ns、hold≥0的工程测试范围；当前FIR8和前一seed3均实际通过严格非负门禁，无需该负setup许可，历史FAIL不追改为PASS。

| 项目 | 状态 / 入口 |
|---|---|
| 已下载版本 | `MEMS_Array_i2s_fir8_auto_20261011`；[发布](fpga/build/MEMS_Array_i2s_fir8_auto_20261011/release.json) / [JTAG](log/i2s_parity/jtag_fir8_auto_20261011/download.json)，SRAM、未写Flash |
| 功能回归 | [FIR8不可变18/18记录](log/i2s_parity/full_regression_fir8_auto_20261011.json)，104项输入、22份向量；六配置RAM11,435,616项检查 |
| 器件时序 | Slow最小setup/hold +0.016/+0.058ns；Fast +0.387/+0.020ns，All Constraints Met |
| 实板数字自测 | [本次联合验收](log/i2s_parity/fir8_auto_hardware_acceptance_20261011.json)PASS_WITH_KNOWN_ISSUES；A–E全通过，C+D 504,694,272样本0错误0缺包，D128路I2S内容通过；原失败全部保留 |
| 真实输入 | [FIR8真实采样](log/i2s_parity/fir8_auto_unity_spool_20261011/analysis.json)143,589帧/47,863包连续；仅DATA1/ch2、3固定负满量程，stickyCLIP及DC拒绝保留 |
| FIR8实现 | 总APM68、FF47,953、LUT28,512；唯一1轮路由1850秒，128通道采样率不变，共同延迟增加约13.02µs |
| 物理验收 | 板上VCCIO、PDM带载与RGMII TXC波形、DAC模拟输出和64对声学补偿待测 |
| 交付范围 | 工程上板联调；PDS Pre-silicon模型和数字通过不代表实板电气、交流幅值或声学验收 |
| 历史结果 | [版本历史](doc/reports/version_history.md)；首版UART常量0、旧时序FAIL及布线超时/取消均保留 |
接入阵列前，断电按板卡丝印将 **J24 设为 VADJ=1.8 V，J20 选择 VADJ 为 L6/L7 供电**，再实测 VCCIO 与 MEMS VDD 均为 1.8 V。软件约束不会改变板上电压；扩展口 A3V3/A5V0 电源针仍为固定电压。

## 使用入口

| 目的 | 文档 |
|---|---|
| 查找全部文档及验证证据 | [文档索引](doc/README.md) |
| 接线、下载与首次采集 | [上板指南](doc/board_bringup.md) |
| 通过 COM3 验证 PHY/MDIO → ARP → UDP | [UART 联调指南](doc/system_uart_debug.md) |
| 选择 I2S 通道、驱动 PCM5102 或标定奇偶补偿 | [音频监听与补偿指南](doc/audio_monitor.md) |
| 不接麦克风验证数字链路 | [内部 PDM 自测](doc/selftest.md) |
| 编写上位机或保存数据 | [接口开发参考](doc/host_protocol_reference.md) · [采集工具指南](doc/host_capture.md) · [本次UDP暂存/离线解析](doc/reports/i2s_fir8_auto_20261011.md#本次工程采集方式) |
| 了解算法、RTL 与校准接口 | [算法规格](doc/algorithm_spec.md) · [RTL 架构](doc/rtl_architecture.md) · [集成指南](doc/integration.md) |
| 查阅旧版结果 | [版本历史](doc/reports/version_history.md) |

## 系统规格

| 项目 | 当前实现 |
|---|---|
| 输入 | 64 根共享 PDM DATA，每线两只麦克风，共 128 通道 |
| 麦克风时钟 | 3.072 MHz；8 个物理输出来自同一分频源，共用相位和复位 |
| 音频输出 | 每通道 48 kHz、24 位有符号 PCM；定位有效通带 20 Hz～16 kHz；新源码默认估计并移除稳定直流 |
| 前处理 | 双相采集 → CIC5 /8 → FIR63 /4 → FIR127 /2 → 启动直流补偿 → 奇偶组增益 → 逐通道增益/偏置校准 |
| I2S 监听 | 通道 0～127 可选，同一单声道复制至 L/R；48 kHz，24 位/32 位槽；SCK=12.288 MHz、BCK=3.072 MHz |
| 传输 | 跨时钟 FIFO → 每包 3 帧 → UDP/IPv4/ARP → RGMII → RTL8211F-CG |
| 数据量 | UDP 负载 1208 字节/包，16,000 包/秒；含线路开销约 163.072 Mbit/s |
| 默认网络 | FPGA `192.168.10.2`，电脑 `192.168.10.1/24`，UDP 源/目的端口 `5000/5000` |
| 调试接口 | COM3，115200 8N1；原 SYS3 与 `s/h/r/t/c` 保留，新增独立 `@I2S` / `@GAIN` 命令及 I2S1 / GAIN1 回帧 |
| 启动条件 | 真实模式无需网络，滤波稳定 96 帧后估计 4096 帧直流，完成审核后从第 4192 帧输出；UDP 和内部 PDM BIST 等待 1000M 全双工及 ARP |
| 默认校准 | 每通道直流估计并冻结；奇偶组和逐通道交流增益均为 1，ROM 后级偏置为 0；UART 可配置奇偶组增益，个体声学灵敏度尚未实测配平 |

[MEMS 手册](doc/IM72D128V01XTMA1.pdf)给出 LR=GND/VDD 两组不同的典型直流水平，并说明它们随时间稳定。手册没有明确可直接写入补偿器的有符号直流码，因此新源码在启动时逐通道估计均值并冻结，避免将直流水平差错误当作交流增益比例。估计期间保持音频静音；满量程、过大或不稳定的均值会被拒绝，异常通道保持原有故障表现。SYS3 新增 bit12/13/14 分别表示启用直流补偿、估计审核结束、至少一个通道被拒绝；审核结束不等于全部通道正常。内部 BIST 旁路直流补偿并保持原黄金向量；便携内核默认禁用估计。详细参数和算术见[算法规格](doc/algorithm_spec.md)。

数据包中的通道号、帧号和 epoch 用于重建同步时间窗，不能用网络到达时刻代替采样时刻。仿真精度与内部自测结果不等于麦克风实际 SNR；阵元坐标、外部带载波形及声学校准仍须实测。

## MEMS 麦克风引脚映射

| 连接器 | 分配 | Bank | I/O 标准 |
|---|---|---|---|
| J10 | CLK0～7 | L6 | LVCMOS18，16 mA，FAST |
| J10 | SCK、BCK、DIN、LRCK | L5 | LVCMOS33，8 mA，FAST，连接 PCM5102 |
| J25 | DATA32～63 | L6 | LVCMOS18 |
| J26 | DATA0～31 | L7 | LVCMOS18 |

全部 72 个麦克风信号位于可调电压的 L6/L7，不使用固定 3.3 V 的 L5。J10 其他未使用引脚不因此变成 L6。DATAk 对应通道 `2k`（LR=GND）和 `2k+1`（LR=VDD）。八路时钟的实际负载分组以阵列接线为准，逻辑通道编号不随分组改变。

下表保留用户原始接线图的左右列与行顺序；不是新增的连接器针号定义。`-` 后为空表示未分配。封装引脚与信号之间的 `PIN-DATAk` / `PIN-CLKk` 写法供构建脚本读取。请结合板卡丝印确认连接器方向。

### J10（40 pin）

| 原图左列 | 原图右列 |
|---|---|
| GND | A5V0 |
| R21-SCK  | R20- |
| N19-BCK  | P19- |
| M25-DIN  | M24- |
| T25-LRCK | T24- |
| R22- | T22- |
| K26- | K25- |
| L25- | L24- |
| L23- | L22- |
| AA25-CLK7 | Y25-CLK6 |
| AB25-CLK4 | AA24-CLK3 |
| AC24- | AB24- |
| R23- | T23- |
| P26- | R26- |
| M26- | N26- |
| M22- | M21- |
| U26-CLK5 | U25-CLK2 |
| AC26-CLK0 | AB26-CLK1 |
| GND | GND |
| A3V3 | A3V3 |

### J25（40 pin）

| 原图左列 | 原图右列 |
|---|---|
| GND | A5V0 |
| V14-DATA34 | U14-DATA38 |
| T18-DATA33 | T17-DATA36 |
| W18-DATA37 | V18-DATA39 |
| U19-DATA35 | T19-DATA60 |
| U20-DATA46 | T20-DATA58 |
| W26-DATA42 | V26-DATA63 |
| Y26-DATA47 | W25-DATA61 |
| Y23-DATA44 | Y22-DATA62 |
| W23-DATA45 | V23-DATA57 |
| Y20-DATA41 | W20-DATA59 |
| W19-DATA43 | V19-DATA53 |
| T15-DATA40 | T14-DATA54 |
| U16-DATA32 | U15-DATA55 |
| V17-DATA56 | V16-DATA51 |
| V21-DATA48 | U21-DATA52 |
| W24-DATA50 | V24-DATA49 |
| AA23- | AA22- |
| GND | GND |
| A3V3 | A3V3 |

### J26（40 pin）

| 原图左列 | 原图右列 |
|---|---|
| GND | A5V0 |
| AC23-DATA2 | AC22-DATA1 |
| AD26-DATA3 | AD25-DATA0 |
| AD24-DATA4 | AD23-DATA16 |
| AF20-DATA10 | AF19-DATA24 |
| AE20-DATA5 | AD20-DATA8 |
| AF18-DATA7 | AE18-DATA25 |
| AF17-DATA6 | AE17-DATA28 |
| AB20-DATA12 | AA20-DATA26 |
| AD17-DATA15 | AC17-DATA9 |
| AC16-DATA14 | AB16-DATA30 |
| W15-DATA13 | W14-DATA29 |
| AE26-DATA11 | AE25-DATA27 |
| AF25-DATA22 | AF24-DATA31 |
| AF23-DATA19 | AE23-DATA17 |
| AD19-DATA21 | AC19-DATA18 |
| AE21-DATA23 | AD21-DATA20 |
| AF22- | AE22- |
| GND | GND |
| A3V3 | A3V3 |

## 千兆网口接口映射

使用 PHY0（RTL8211F-CG）。PHY 芯片支持 10/100/1000M，当前系统只在 1000M 全双工下发送 UDP；真实模式采集及 I2S 可独立运行。

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

## 板级时钟与控制

| 接口 | FPGA 引脚 | 用途 |
|---|---|---|
| 27 MHz 参考 | D18 | 27 → 96 → 122.88 MHz 音频 PLL 链；独立 UART 观察时基 |
| 125 MHz 差分参考 | N3 / N2 | SSTL15D_I、1.5 V；PLL 倍频 250 MHz，再单沿二分频为 125 MHz 网络时钟 |
| UART RX / TX | B24 / C24 | FPGA 方向，3.3 V，板载串口桥连接 COM3 |
| KEY0 / KEY1 | C22 / C23 | 兼容保留全局复位与模式切换；联调以 UART 为主 |

完整顶层共 103 个约束端口，包含新增四根 I2S 输出。I2S 使用固定 3.3 V 的 L5，MEMS 使用 1.8 V 的 L6/L7；J10 同时含两种电压的信号，不能把整个连接器视为同一 Bank。八路 CLK 同源不表示焊盘零偏斜；PDM 外部往返传播预算为 20 ns，真实麦克风引脚处的时钟边沿与占空比待测。详细电气条件见[上板指南](doc/board_bringup.md)。

## 工程与验证入口

| 内容 | 入口 |
|---|---|
| 板级顶层 / 可移植前处理 | [mems_array_pg2l200h.sv](rtl/board/mems_array_pg2l200h.sv) / [mems_array_top.sv](rtl/mems_array_top.sv) |
| 可移植网络内核 | [mems_ethernet_core.sv](rtl/net/mems_ethernet_core.sv) |
| 浮点/定点模型与 Cmodel | [lib/model](lib/model) / [mems_rm.cpp](lib/cmodel/mems_rm.cpp) |
| 引脚与时序约束 | [fpga/constraints](fpga/constraints) |
| 完整构建与发布检查 | [构建操作](doc/board_bringup.md#构建与发布复现) / [发布检查说明](fpga/scripts/RELEASE_CHECK.md) |
| 最新功能回归 | [自动系统验证报告](doc/reports/system_verification.md) / [FIR8不可变完整回归](log/i2s_parity/full_regression_fir8_auto_20261011.json)，18/18 PASS，104项输入、22份向量 |

在工程根目录执行 `python sim/verify_all.py` 进行完整回归；`sim/sim.bat` 仅运行前处理层。依赖和分层运行方式见[集成指南](doc/integration.md)。最初仅做前处理的需求保存在[原始需求记录](doc/history/original_requirements.md)。
