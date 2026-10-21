# PG2L200H 上板与采集

[文档索引](README.md) · [当前工作状态](../log/i2s_parity/work_status.json) · [UART 联调](system_uart_debug.md) · [I2S 与补偿](audio_monitor.md)

当前已发布版本：**`MEMS_Array_i2s_parity_fir_fixed_result_20261009`**，盘古 MINI-200H、PG2L200H / FBB676 / -6。2026-10-09 **18/18 项功能回归、严格发布检查和实板数字自测通过**，14:40:49 完成 JTAG 下载。128 路 UART 通道选择已逐路实测通过；完整身份及验收记录见[本版本交付报告](reports/i2s_parity_fir_fixed_result_20261009.md)。DATA1/ch2、3 仍固定负满量程，实际 L6/L7 电压、DAC 模拟输出与声学校准尚未完成验收。

历史版本的结果只用于追溯：[第一版](reports/i2s_parity_20261009.md)网络通过，但 UART 数字通道号被编译为常量 0；[UART 修复候选](reports/i2s_parity_uartfix_timing_20261009.md)两轮时序失败，未生成位流；[timingfix4 参数对照](reports/i2s_parity_timingfix4_20261009.md)及中间候选的未完成布线以超时或主动取消结束，时序未知。它们不能替代本版本的发布和实测证据。

## 1. 确认位流与供电

当前位流为 [mems_array_pg2l200h.sbit](../fpga/build/MEMS_Array_i2s_parity_fir_fixed_result_20261009/generate_bitstream/mems_array_pg2l200h.sbit)，位于 `fpga/build/MEMS_Array_i2s_parity_fir_fixed_result_20261009/generate_bitstream/`。其 [release.json](../fpga/build/MEMS_Array_i2s_parity_fir_fixed_result_20261009/release.json) 已为 `status=PASS`、`release_authorized=true`。再次下载前仍须核对 `evidence.bitstream.sha256` 与实际文件一致；`pre_bit_check.json` 只是生成前检查。当前发布范围为 `engineering_board_bringup`，不代表外部电气和声学条件已全部验收。

1. 断电后按板卡丝印将 J24 选择为 VADJ=1.8 V，J20 选择 VADJ 为 L6/L7 供电。
2. 接入阵列前实测 **L6/L7 VCCIO 与 MEMS VDD 均为 1.8 V**。
3. 核对共地。扩展口 A3V3/A5V0 仍为固定电压，不会随 Bank 设置变成 1.8 V。

依据为[开发板硬件手册](盘古MINI系列开发板硬件指导手册_V1.3.pdf)第 12、41 页。L5 固定 3.3 V；当前麦克风信号全部移至 L6/L7。不要将旧四路、3.3 V 位流用于当前阵列直连。

## 2. 接线与电脑配置

完整引脚表以[项目 README](../README.md#mems-麦克风引脚映射)为准。

| 接口 | 连接与配置 |
|---|---|
| J10 MEMS | CLK0～7，3.072 MHz 同源；L6、LVCMOS18、16 mA、FAST |
| J10 I2S | SCK/BCK/DIN/LRCK，L5 固定 3.3 V、LVCMOS33、8 mA、FAST；接线见[音频指南](audio_monitor.md#接线与接口时序) |
| J26 / J25 | DATA0～31 / DATA32～63，LVCMOS18；64 根共享线接 128 只麦克风 |
| LR | 每对分别接 GND、VDD；DATAk 对应通道 `2k`、`2k+1` |
| 板载时钟 | D18：27 MHz；N3/N2：125 MHz 差分参考 |
| UART | FPGA RX=B24、TX=C24，3.3 V；COM3、115200 8N1、无流控 |
| 网口 | PHY0 接电脑或千兆交换机；电脑 `192.168.10.1/24`，FPGA `192.168.10.2`，UDP 5000 |

八路 CLK 的物理负载分组以实际阵列接线为准；均分时每组 16 只麦克风。调试使用 UART，KEY0/KEY1 和 LED 的兼容功能见[自测指南](selftest.md)。

## 3. JTAG 下载

PDS 实际生成的带头位流扩展名是 `.sbit`。在 Pango **Fabric Configuration** 中连接板卡 JTAG，选择 **Boundary Scan**，执行 **Scan Device**，确认识别到 PG2L200H；通过 **Assign New Configuration File** 指定上述已发布 `.sbit`，执行 **Program**。这些操作对应安装目录内 `doc/Fabric_Configuration_User_Guide.pdf` 的 4.3 节。

首次验证使用 JTAG 配置 FPGA；这是易失配置，重新掉电后需要再次下载。需要上电自动加载时，再按实际板卡 Flash 型号及 Pango 配置指南建立 Flash 下载任务；原始 `.bin` 的存在不能替代 Flash 器件、地址与配置模式的选择。

配置后自动执行 PLL 锁定、128 路校准装载及 PHY 初始化。旧发布版本在校准后启动 50 ms PDM 等待并丢弃前 96 帧滤波瞬态。正在验证的新源码还会逐通道估计 4096 帧直流并冻结，真实首帧为 4192；启动时保持声场稳定，估计期间 I2S 发零。前处理和 I2S 无需等待网络；UDP 等待 1000M 全双工及 ARP，从完整帧开始发送。内部 PDM BIST 仍在网络就绪后启动，旁路直流估计、首帧仍为 96。默认监听通道 0、奇偶与逐通道交流增益 1，ROM 后级偏置 0；单位增益不会关闭新直流补偿。

## 4. UART 与数字链路验收

先关闭其他串口助手，在工程根目录执行只读状态采集：

```powershell
.\lib\host\capture_system_uart.ps1 -Port COM3 -Seconds 15
```

确认收到 `SYS3`，依次检查时钟/复位、PHY/MDIO、ARP、UDP。判据和命令见[UART 联调指南](system_uart_debug.md)。随后按[内部 PDM 自测](selftest.md)执行自动自测和电脑逐样本校验；串口发送计数增加本身不能证明电脑已收到数据。

新增 I2S/奇偶配置的数字验证运行 `lib/host/selftest_audio_board.ps1`，完整步骤和 DAC 模拟验收见[音频指南](audio_monitor.md#数字实板自测与-dac-验收)。脚本结束恢复原监听通道并将组增益恢复为 1；0.5/0.75 是测试值，不是测得的补偿系数。

本版本已完成 0～127 通道逐路配置、OFF、非法输入拒绝及复位重放检查；偶组、奇组分别置零时，对应 64 路均精确为 0。网络 BIST 两次共比较 506,273,664 个样本，数值、连续性、错误标志及主机错误均为 0；I2S 全通道自测内容也通过。结束后恢复真实输入、两组单位增益和 I2S 通道 0 开启。详细计数与原始日志见[交付报告](reports/i2s_parity_fir_fixed_result_20261009.md#实板数字自测)。后续测试仍需记录位流身份、接线/电压、UART 日志与 PCM 捕获前缀。

## 5. 真实阵列采集

先确认当前模式。若 `SelftestMode=true`，通过 UART 发送一次 `t` 并确认新鲜状态变为 false；也可用 `r` 复位回真实输入模式。全局复位后另开新的捕获文件，避免 epoch 重用。

```powershell
python lib/host/receive_pcm.py --bind 192.168.10.1 --output captures/run01 --seconds 30
```

输出前缀必须未使用。连续采集可省略 `--seconds`，用 Ctrl+C 正常结束。30 秒原始 PCM 约 553 MB，另须预留逐帧元数据空间。

接收器生成 `.pcm24le`、`.frames.jsonl`、`.summary.json`。同一定位时间窗须同源、同 epoch、frame_id 连续，并通过质量标志检查。主机到达/写盘时间不代表阵元采样时间。若 bit2=1（处理调度错误），即使帧号连续也应停止将该会话用于定位。读取方法见[采集指南](host_capture.md)。

本版本另捕获了 3 秒真实输入，共 47,969 包、143,907 帧，包号与帧号连续。DATA1（J26/AC22）的通道 2、3 全部样本均为 −8,388,608，AC RMS=0；143,907 帧均保留 sticky saturation 标志。连续传输通过不能证明阵列输入合格，下一步优先检查该共享 DATA 路径、两只麦克风的供电/LR 接法及实际 PDM 波形，见[真实数据记录](reports/i2s_parity_fir_fixed_result_20261009.md#真实麦克风数据与下一步排查)。

## 6. 实板电气与声学边界

| 待测项目 | 条件 / 判据 |
|---|---|
| 麦克风供电 | 实测 MEMS VDD 与 L6/L7 VCCIO 为 1.8 V |
| PDM 带载波形 | 实际麦克风引脚处 3.072 MHz，占空比 48%～52%，上升/下降时间 ≤13 ns |
| PDM 外部路径 | 时钟扇出/缓冲、连接器及往返布线合计预算 ≤20 ns |
| I2S 与 DAC | PCM5102 引脚处确认标准 I2S、供电/FMT/XSMT、时钟边沿及外部相对延迟预算；再测模拟 L/R 输出 |
| RGMII | PHY 处 TXC 占空比 45%～55%，周期 7.2～8.8 ns；20%～80% 上升/下降时间 ≤0.75 ns；PCB 相对偏斜预算 ±0.2 ns |
| 实际阵列 | 检查全部通道的饱和、极性、增益、时延和阵元坐标，再进行声学校准 |

八路时钟同源及 16 mA 驱动不等于实际负载已合格。本版本在 PDS 2022.2-SP6.4 的原 `Pre-silicon` 模型及现行约束下全部时序通过：慢角最小 setup 为 0.021 ns、hold 为 0.037 ns，快角最小 hold 为 0.020 ns。裕量较小；发布文件的无条件板级验收仍为 false，TXC 占空比/抖动敏感性检查未通过，需实测外部条件。零增益归零和内部 I2S 串行监测不能代替 DATA1 故障定位、DAC 模拟输出或 64 对声学幅值验收。

## 构建与发布复现

在工程根目录执行。新目录名带时间戳，避免覆盖已发布证据：

```powershell
python sim/verify_all.py
python -m unittest discover -s fpga/scripts/tests -v
$buildName = 'MEMS_Array_i2s_parity_fir_fixed_result_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
python fpga/scripts/build.py --stage gen_bit_stream --build-name $buildName --place-seed 2 --placement-decongestion 5 --placement-initial-method Center --pnr-timeout-minutes 180
```

上述 Center、疏散 5、种子 2 是本次完整构建的实际配置；新构建须以自己的最终 `release.json` 为准。本次首轮已完整布通并保存且全部约束通过，第二轮可选优化停止后通过既有检查点流程重新导出和严格校验再生成位流；完整过程见[交付报告](reports/i2s_parity_fir_fixed_result_20261009.md#实现与布线修正)。不要将中断的优化日志视为普通成功。脚本默认的扩散/超时参数与上述配置不同，请保留显式参数。`--start-stage` 只用于诊断，不用于常规发布。完整回归强制包含 `fir_ram`，绑定真实 RAM 检查的结果及输入 SHA-256，详见[集成指南](integration.md)。

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

本版本已记录实板连续网络采集和数字自测；真实扇出波形、电压、DAC 模拟输出及声学性能仍需按上述步骤实测记录。
