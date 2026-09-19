# PG2L200H 上板与采集

> 2026-09-20 当前版本：八路同源时钟、1.8 V 麦克风接口已完成并通过发布检查。推荐[下载位流](../fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/generate_bitstream/mems_array_pg2l200h.sbit)，[发布记录](../fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/release.json)为 PASS。接线和供电条件见[当前发布报告](reports/clk8_18v_update.md)。接入阵列前必须实测确认 L6/L7 为 1.8 V。下文涉及旧四路 3.3 V 接线、2026-09-17 自测位流的内容为历史记录。

本指南对应盘古 MINI-200H、PG2L200H / FBB676 / -6，以及 README 中确认的 J10、J25、J26、PHY0 接线。功能仿真结果见 [系统验证报告](reports/system_verification.md)，发布依据是构建目录内的 `release.json`。文件存在本身不代表该版本通过发布检查。

2026-09-17 增加按键和 LED 自测，当时的构建目录为 `fpga/build/MEMS_Array_selftest/`。旧版已发布位流保留在 `fpga/build/MEMS_Array/`，不包含自测；不要混用两版工程和发布记录。新增功能与模拟数据验收见 [selftest.md](selftest.md)。

历史自测构建于2026-09-17 02:28完成，当时的 [release.json](../fpga/build/MEMS_Array_selftest/release.json) 为PASS且允许工程上板联调。资源、时序、位流校验值及尚需实测的边界见 [自测实现报告](reports/selftest_implementation.md)。

## 构建与发布文件

在工程根目录执行：

```powershell
python sim/verify_all.py
python fpga/scripts/build.py --stage gen_bit_stream --build-name MEMS_Array_uart_clk8_18v_spread3_long --placement-decongestion 3 --pnr-timeout-minutes 180
```

第一条命令重新运行数值模型、RTL、厂商原语和上位机回归。第二条从编译开始执行综合、器件映射、布局布线和双角时序检查，检查通过后才生成位流，并再次核对产物。修改 RTL、系数、测试或约束后须重新执行相应验证和完整构建。`--start-stage` 只用于诊断，不能用于发布。

脚本缺省使用本机已安装的 PDS 2022.2-SP6.4；其他安装位置用 `--pango` 指定，许可证用 `PANGO_LICENSE_FILE` 环境变量或 `--license-file` 指定。详细的工具与 Python 依赖见 [集成指南](integration.md)。

| 文件 | 用途 |
|---|---|
| `fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/MEMS_Array.pds` | 编译阶段 Pango 工程；完整重建使用上述脚本 |
| `fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/generate_bitstream/mems_array_pg2l200h.sbit` | Pango 带信息头的 FPGA 配置位流 |
| `fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/generate_bitstream/mems_array_pg2l200h.bin` | 无信息头的原始配置数据 |
| `fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/release.json` | 发布状态、源代码、回归、报告与位流 SHA-256 |
| `fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/report_timing/mems_array_pg2l200h.rtr` | 实际布线后的慢角、快角时序报告 |

烧录前应确认 `release.json` 的 `status` 为 `PASS`，且 `release_authorized` 为 `true`，并使用其中记录的位流。`pre_bit_check.json` 仅是生成前检查，不是发布结果。原有 `fpga/MEMS_Array.pds` 与自动构建工程不同，打开工程时应选择上述 `fpga/build` 下的文件。

当前安装的 PDS 2022.2-SP6.4 对 PG2L200H 的原始时序报告标注为 `Pre-silicon`。发布记录保留该真实模型类型；即使双角时序通过，也不能把它写成基于 `Production` 模型的签核或实板测量。更换厂商器件模型或工具版本后，应重新完成构建和时序验证。

位流的发布范围为工程上板联调（`engineering_board_bringup`）。厂商模型中的双角时序、引脚偏斜和名义占空比须通过检查；PLL 手册的 180 ps 输出抖动没有说明峰峰值、逐沿误差或 RMS 口径，不能据此宣称实际 TXC 的全部瞬时占空比已经得到保证。发布证据保留按逐沿 ±180 ps 计算的保守敏感性分析，以及实际布线所允许的相邻边沿抖动上界。首次上板须测量 PHY 的 TXC 引脚，确认实际占空比在 45%～55%、周期在 7.2～8.8 ns，并检查 RGMII 的 20%～80% 上升/下降时间不超过 0.75 ns；该项板级资格验证与 FPGA 模型时序检查分别记录。

## 板卡连接

1. 核对芯片封装与速度等级，按 README 连接 64 根共享 PDM DATA。每对麦克风的 LR 必须分别接 GND、VDD；DATAk 对应通道 `2k`（LR=GND）和 `2k+1`（LR=VDD）。共同参考地不可缺少。
2. 按 README 将 J10 的 CLK0～7 接到八组麦克风，全部为同源 3.072 MHz；均分时每组 16 只，实际以阵列接线为准。J26 接 DATA0～31，J25 接 DATA32～63。所有麦克风信号采用 LVCMOS18，CLK 为 16 mA/FAST。断电后将 J24 选择为 VADJ=1.8 V、J20 选择 VADJ 给 L6/L7 供电，接入阵列前实测 VCCIO 和 MEMS VDD 均为 1.8 V。扩展口 A3V3/A5V0 电源针不随此设置变成 1.8 V。
3. 确保 D18 的 27 MHz 与 N3/N2 的 125 MHz 板载参考可用。音频使用两级 PLL；网络使用独立 PLL 倍频至 250 MHz，再以连续上升沿二分频生成 125 MHz。任一 PLL 失锁都会重新执行全局启动流程。C22 的 KEY0 是低有效全局复位。
4. 状态反馈和测试控制使用 COM3、115200 8N1，无流控，见 [UART 联调指南](system_uart_debug.md)。UART RX=B24、TX=C24；原 KEY0/KEY1 功能兼容保留。
5. PHY0 千兆口连接电脑或同一局域网的千兆交换机。把接收网卡设为 `192.168.10.1/24`，允许接收 UDP 5000；FPGA 为 `192.168.10.2`。本设计只在协商为 1000M 全双工时采集。

阵列外部时序条件须由硬件实现满足：PDM 外部传播预算 20 ns 包括时钟缓冲、连接器与往返布线；在实际麦克风引脚处，3.072 MHz 时钟的占空比须在 48%～52%，上升/下降时间须不超过 13 ns。现有资料没有给出 CLK 输入电容，因此不能仅凭 FPGA 时序通过认定每个时钟输出脚的实际阵列负载已经合格。RGMII PCB 相对走线偏差预算为 ±0.2 ns。具体预算与约束以最终实现报告为准。

## 下载与启动

PDS 实际生成的带头位流扩展名是 `.sbit`。在 Pango **Fabric Configuration** 中连接板卡 JTAG，选择 **Boundary Scan**，执行 **Scan Device**，确认识别到 PG2L200H；通过 **Assign New Configuration File** 指定上述已发布 `.sbit`，执行 **Program**。这些操作对应安装目录内 `doc/Fabric_Configuration_User_Guide.pdf` 的 4.3 节。

首次验证使用 JTAG 配置 FPGA；这是易失配置，重新掉电后需要再次下载。需要上电自动加载时，再按实际板卡 Flash 型号及 Pango 配置指南建立 Flash 下载任务；原始 `.bin` 的存在不能替代 Flash 器件、地址与配置模式的选择。

配置后硬件自动执行 PLL 锁定、128 路校准写入、PHY 复位和初始化、千兆协商、50 ms 麦克风启动等待及前 96 帧丢弃，无需通过主机发送启动命令。网络协商时间取决于对端。默认校准为增益 1、偏置 0。

在工程根目录开始 30 秒采集：

```powershell
python lib/host/receive_pcm.py --output captures/run01 --seconds 30
```

文件前缀须未使用。连续运行可省略 `--seconds`，用 Ctrl+C 正常结束。原始 PCM 每秒约 18.432 MB，此外还会保存逐帧元数据；30 秒的原始 PCM 约 553 MB，须预留元数据空间。

输出为 `.pcm24le`、`.frames.jsonl`、`.summary.json` 三个配套文件。每个采样帧有 128 个有符号 24 位小端数，按通道升序排列。用于 SRP-PHAT 的同一时间窗应具有相同 epoch、连续 frame_id，并通过状态检查；主机接收时间和文件写入时间不是阵元采样时间。断线重连会创建新会话，硬复位、重新烧录或 PLL 失锁恢复后须使用新文件前缀重启接收器。

若 flags.bit2=1，前处理发生调度错误，连续帧号也不能证明真实采样时间连续，该会话应停止用于定位。元数据的 `continuous_with_previous=true` 只表示帧号相邻，不能替代质量检查。

## 首次检查与故障定位

| 现象 | 检查项 |
|---|---|
| 没有数据 | 电源、两个参考时钟、KEY0、网线和千兆全双工协商；IP 是否为 192.168.10.1，UDP 5000 是否被其他程序占用或被防火墙阻止 |
| 能看到 ARP、收不到 UDP | 上位机是否回复 FPGA 针对 192.168.10.1 的 ARP；网卡与程序监听/源地址过滤设置 |
| `ping` 不通 | 本设计只接收 ARP，不实现 ICMP；以 UDP 接收和包校验结果判断业务链路 |
| 主机队列丢包 | 查看 `host_queue_dropped_packets`，减少同时运行的任务、检查磁盘吞吐，并按接收指南调整缓冲 |
| 包号或帧号有缺口 | 查看逐帧元数据和总结，切断定位时间窗；帧号缺口不能按连续采样直接使用 |
| flags 非零 | bit0 饱和、bit1 前处理溢出、bit2 调度错误、bit3 帧结构错误；bit4仅表示自测数据，bit5表示自测失败。错误位在同一会话内保持，不能把每个后续标志都计为一次新故障 |
| 通道无声或成对异常 | DATA 与 LR 接线、真实负载下的时钟边沿/电压、麦克风供电和 DATA 有效窗口 |

稳定输入情况下，正常采集应没有格式错误或新增缺帧。用实际阵列完成各通道极性/增益/延迟测量后，可通过 `lib/model/export_board_calibration.py` 导入 128 行增益 Q22、偏置 Q30 并重新构建；阵元坐标与声学延迟校准用于定位算法，不能由 FPGA 管脚顺序推断。上位机字段、缺帧统计和文件读取方法详见 [接收指南](host_capture.md)。

本工程的仿真及 FPGA 实现报告分别证明数字功能和指定器件上的静态时序；实板连续网络采集、真实扇出波形和声学性能需要按上述步骤实测记录。
