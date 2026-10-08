# PG2L200H 上板与采集

[文档索引](README.md) · [当前发布报告](reports/clk8_18v_update.md) · [UART 联调](system_uart_debug.md)

适用版本：**`MEMS_Array_uart_clk8_18v_spread3_long`**，盘古 MINI-200H、PG2L200H / FBB676 / -6。2026-09-20 工程发布检查 PASS；本版尚未下载到板卡，实际 L6/L7 电压及本版实板功能待确认。以下为待执行步骤。

## 1. 确认位流与供电

使用[当前 .sbit](../fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/generate_bitstream/mems_array_pg2l200h.sbit)。烧录前确认同目录构建的 [release.json](../fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/release.json) 中 `status=PASS`、`release_authorized=true`，且位流 SHA-256 与[发布报告](reports/clk8_18v_update.md)一致。`pre_bit_check.json` 仅是生成前检查。

1. 断电后按板卡丝印将 J24 选择为 VADJ=1.8 V，J20 选择 VADJ 为 L6/L7 供电。
2. 接入阵列前实测 **L6/L7 VCCIO 与 MEMS VDD 均为 1.8 V**。
3. 核对共地。扩展口 A3V3/A5V0 仍为固定电压，不会随 Bank 设置变成 1.8 V。

依据为[开发板硬件手册](盘古MINI系列开发板硬件指导手册_V1.3.pdf)第 12、41 页。L5 固定 3.3 V；当前麦克风信号全部移至 L6/L7。不要将旧四路、3.3 V 位流用于当前阵列直连。

## 2. 接线与电脑配置

完整引脚表以[项目 README](../README.md#mems-麦克风引脚映射)为准。

| 接口 | 连接与配置 |
|---|---|
| J10 | CLK0～7，3.072 MHz 同源；LVCMOS18、16 mA、FAST |
| J26 / J25 | DATA0～31 / DATA32～63，LVCMOS18；64 根共享线接 128 只麦克风 |
| LR | 每对分别接 GND、VDD；DATAk 对应通道 `2k`、`2k+1` |
| 板载时钟 | D18：27 MHz；N3/N2：125 MHz 差分参考 |
| UART | FPGA RX=B24、TX=C24，3.3 V；COM3、115200 8N1、无流控 |
| 网口 | PHY0 接电脑或千兆交换机；电脑 `192.168.10.1/24`，FPGA `192.168.10.2`，UDP 5000 |

八路 CLK 的物理负载分组以实际阵列接线为准；均分时每组 16 只麦克风。调试使用 UART，KEY0/KEY1 和 LED 的兼容功能见[自测指南](selftest.md)。

## 3. JTAG 下载

PDS 实际生成的带头位流扩展名是 `.sbit`。在 Pango **Fabric Configuration** 中连接板卡 JTAG，选择 **Boundary Scan**，执行 **Scan Device**，确认识别到 PG2L200H；通过 **Assign New Configuration File** 指定上述已发布 `.sbit`，执行 **Program**。这些操作对应安装目录内 `doc/Fabric_Configuration_User_Guide.pdf` 的 4.3 节。

首次验证使用 JTAG 配置 FPGA；这是易失配置，重新掉电后需要再次下载。需要上电自动加载时，再按实际板卡 Flash 型号及 Pango 配置指南建立 Flash 下载任务；原始 `.bin` 的存在不能替代 Flash 器件、地址与配置模式的选择。

配置后自动执行 PLL 锁定、128 路校准装载及 PHY 初始化。只有校准完成、1000M 全双工链路建立且 ARP 对端地址有效后，才启动 50 ms PDM 等待并丢弃前 96 帧滤波瞬态。无需上位机启动命令；网络协商时间取决于对端。默认使用增益 1、偏置 0。

## 4. UART 与数字链路验收

先关闭其他串口助手，在工程根目录执行只读状态采集：

```powershell
.\lib\host\capture_system_uart.ps1 -Port COM3 -Seconds 15
```

确认收到 `SYS3`，依次检查时钟/复位、PHY/MDIO、ARP、UDP。判据和命令见[UART 联调指南](system_uart_debug.md)。随后按[内部 PDM 自测](selftest.md)执行自动自测和电脑逐样本校验；串口发送计数增加本身不能证明电脑已收到数据。

每次测试记录位流 SHA-256、接线/电压、UART 日志与 PCM 捕获前缀。旧版的网络实测记录不用于判定本版通过。

## 5. 真实阵列采集

先确认当前模式。若 `SelftestMode=true`，通过 UART 发送一次 `t` 并确认新鲜状态变为 false；也可用 `r` 复位回真实输入模式。全局复位后另开新的捕获文件，避免 epoch 重用。

```powershell
python lib/host/receive_pcm.py --bind 192.168.10.1 --output captures/run01 --seconds 30
```

输出前缀必须未使用。连续采集可省略 `--seconds`，用 Ctrl+C 正常结束。30 秒原始 PCM 约 553 MB，另须预留逐帧元数据空间。

接收器生成 `.pcm24le`、`.frames.jsonl`、`.summary.json`。同一定位时间窗须同源、同 epoch、frame_id 连续，并通过质量标志检查。主机到达/写盘时间不代表阵元采样时间。若 bit2=1（处理调度错误），即使帧号连续也应停止将该会话用于定位。读取方法见[采集指南](host_capture.md)。

## 6. 实板电气与声学边界

| 待测项目 | 条件 / 判据 |
|---|---|
| 麦克风供电 | 实测 MEMS VDD 与 L6/L7 VCCIO 为 1.8 V |
| PDM 带载波形 | 实际麦克风引脚处 3.072 MHz，占空比 48%～52%，上升/下降时间 ≤13 ns |
| PDM 外部路径 | 时钟扇出/缓冲、连接器及往返布线合计预算 ≤20 ns |
| RGMII | PHY 处 TXC 占空比 45%～55%，周期 7.2～8.8 ns；20%～80% 上升/下降时间 ≤0.75 ns；PCB 相对偏斜预算 ±0.2 ns |
| 实际阵列 | 检查全部通道的饱和、极性、增益、时延和阵元坐标，再进行声学校准 |

八路时钟同源及 16 mA 驱动不等于实际负载已合格。当前使用 PDS 2022.2-SP6.4 的 `Pre-silicon` 模型，发布范围为 `engineering_board_bringup`。名义模型时序通过；额外逐沿 ±180 ps 假设下的 TXC 敏感性分析仍为 FAIL，真实占空比/抖动资格为 UNCONFIRMED，见[发布报告](reports/clk8_18v_update.md)。

## 构建与发布复现

在工程根目录执行。新目录名带时间戳，避免覆盖已发布证据：

```powershell
python sim/verify_all.py
python -m unittest discover -s fpga/scripts/tests -v
$buildName = 'MEMS_Array_uart_clk8_18v_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
python fpga/scripts/build.py --stage gen_bit_stream --build-name $buildName --place-seed 2 --placement-decongestion 3 --placement-initial-method Center --pnr-timeout-minutes 180
```

这些是推荐版本使用的实现参数；新构建须以其自己的最终 `release.json` 为准。脚本默认的扩散/超时参数与本次推荐参数不同，请保留显式参数。`--start-stage` 只用于诊断，不用于常规发布。

依赖见[集成指南](integration.md)。脚本默认使用本机 PDS 2022.2-SP6.4；安装位置可用 `--pango` 指定，许可证用 `PANGO_LICENSE_FILE` 或 `--license-file`。生成的 `MEMS_Array.pds` 是编译阶段工程，完整重建使用上述脚本，以包含映射后宏布局、双角检查和发布验证。

| 构建目录内文件 | 用途 |
|---|---|
| `generate_bitstream/mems_array_pg2l200h.sbit` | 带信息头的配置位流 |
| `generate_bitstream/mems_array_pg2l200h.bin` | 原始配置数据 |
| `manifest.json` / `release.json` | 构建记录 / 最终发布与校验值 |
| `report_timing/mems_array_pg2l200h.rtr` | 布线后慢角、快角时序报告 |

## 故障定位

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
