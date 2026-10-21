# 内部 PDM 自测与上位机验收

[文档索引](README.md) · [UART 联调](system_uart_debug.md) · [音频监听](audio_monitor.md) · [上板指南](board_bringup.md)

当前版本 **`MEMS_Array_i2s_parity_fir_fixed_result_20261009`** 已通过[18/18 项功能回归](../log/i2s_parity/full_regression_fir_fixed_result_20261009.json)、严格发布检查及实板数字自测，2026-10-09 14:40:49 完成 JTAG 下载。UART 128 路选择、奇偶独立零增益、PHY/ARP/UDP 黄金数据及 I2S 全通道内容均通过；原始结果见[本版本交付报告](reports/i2s_parity_fir_fixed_result_20261009.md)。DATA1/ch2、3 的真实输入仍固定负满量程，电压、DAC 模拟输出和声学配平尚未验收。

[第一版](reports/i2s_parity_20261009.md)的网络 BIST 通过，但 UART 数字通道号恒为 0；[UART 修复候选](reports/i2s_parity_uartfix_timing_20261009.md)两轮时序失败，未生成位流。[timingfix4 参数对照](reports/i2s_parity_timingfix4_20261009.md)及其他未完成布线候选属于历史记录，超时/主动取消后的时序结论为未知，不能记为已测得的时序失败或本版本通过。

内部产生确定性 PDM，经过双相采集、滤波、奇偶补偿旁路、逐通道校准、打包与千兆 UDP 发送；不连接麦克风也可验证数字链路，不能检测外部供电、接线、时钟负载或声学性能。

新源码增加真实模式的启动直流估计，完整新位流仍待验证。内部 BIST 不训练、不扣除直流，乘法保持单位增益，不覆盖用户保存的组增益，原第 96 帧及黄金样本不变。退出 BIST 后真实模式重新等待 96 帧滤波稳定并估计 4096 帧，从第 4192 帧输出；期间 I2S 发零。普通真实模式掉网保持冻结直流。SYS3 的估计审核结束位不作为 BIST 通过条件，也不证明全部真实麦克风正常。

## 1. 准备

按[上板指南](board_bringup.md)确认供电、下载当前位流。电脑网卡设为 `192.168.10.1/24`，连接千兆 PHY0，允许 UDP 5000。COM3 使用 115200 8N1、无流控，并关闭其他占用串口的程序。

## 2. 通过 UART 进入自测

在工程根目录执行：

```powershell
.\lib\host\capture_system_uart.ps1 -Port COM3 -Seconds 30 -SelfTest
```

脚本先确认 SYS3，再发 `r` 复位；等待时钟、校准、PHY 与 ARP 就绪后发 `t` 切换。内部 BIST 保持网络门控，未连接网络或尚未解析 ARP 时不能完成本地与发送两级验收。正常真实音频则在校准完成后独立运行 I2S，二者启动条件不同。结束后脚本保持自测，便于继续接收数据。不要再盲发 `t`，因为它会切换回真实输入。

| 判据 | 期望 |
|---|---|
| 时钟与状态新鲜度 | `ClocksHealthy=true`、`AudioFresh=true`、`EthFresh=true` |
| 网络 | `PhyReady=true`、`LinkUp=true`、`PeerValid=true`，`UdpSent` 持续增长 |
| 模式 / 本地自测 | `SelftestMode=true`、`SelftestPass=true`、`SelftestFail=false` |
| 发送自测 | `SelftestTxPass=true`、`SelftestTxFail=false` |
| 数据链错误 | `Overflow=false`、`ProcessingError=false`、`TxError=false`、`FramingError=false` |

UART 摘要中的 `FpgaSelftestPass=true` 只覆盖 FPGA 端。默认本地通过门限为 48,000 帧，发送门限为 16,000 个完整 UDP 包；达标后持续检查，不会停止发送。详细字段、超时与快照边界见[UART 指南](system_uart_debug.md)。

## 3. 电脑接收并逐样本比较

使用未用过的文件前缀：

```powershell
python lib/host/receive_pcm.py --bind 192.168.10.1 --output captures/bist01 --seconds 10
python lib/host/verify_selftest.py --capture captures/bist01 --min-frames 48000 --output captures/bist01.check.json
```

通过条件：`status=PASS`，`mismatching_frames=0`、`error_flag_packets=0`、`continuity_errors=0`，主机队列丢弃为 0。稳定阶段预期约 16,000 包/秒、48,000 帧/秒；短时间统计受电脑调度影响。

接收器可以包含普通包，校验器会统计并跳过它们；不足 48,000 自测帧判失败。稳定区间 PASS 不覆盖先前的启动/切换过程。验证切换首包时，先开接收器，再发 `t`，按新 epoch 检查首帧与连续性。硬复位、重新下载或 PLL 失锁后使用新文件前缀。

本版本实板的两次黄金比较结果如下，数值错误、错误标志、连续性错误、主机队列丢包和无效负载均为 0：

| 捕获 | BIST 包 | BIST 帧 | 比较样本 | 普通包跳过 |
|---|---:|---:|---:|---:|
| C：进入 BIST 与网络链路 | 198,424 | 595,272 | 76,194,816 | 25,900 |
| D：70 秒持续 BIST / I2S 内容检查 | 1,119,997 | 3,359,991 | 430,078,848 | 0 |

C 跳过的是启动/切换前的普通包，不能把它们算为丢包或纳入同一 BIST 黄金序列。D 同时完成全部 128 通道、每通道 4 个 I2S 快照的非零内容检查，稳态欠载无新增；0.5/0.75 配置时 BIST 仍单位增益旁路。详见[实板数字自测记录](reports/i2s_parity_fir_fixed_result_20261009.md#实板数字自测)。

## 4. 恢复真实输入

确认当前 `SelftestMode=true` 后发送一次 `t`：

```powershell
.\lib\host\capture_system_uart.ps1 -Port COM3 -Seconds 5 -Command t
```

等待新鲜状态中 `SelftestMode=false`。模式切换会停止前端并清空旧流，重载正常校准 ROM；奇偶增益恢复使用已保留的配置，I2S 使用已有期望通道和开关。正常模式完成重载后，即使没有 PHY 链路或 ARP 对端，也会重新启动真实 PDM 与 I2S；网络满足条件后开始新 epoch。正常模式下仅拔插网线不会重启前端时间轴，不能把重连首个网络帧强制解释为 frame_id=96。未接阵列时真实输入没有声学意义；自测包 bit4=1，不得送入定位算法。

本次 E 阶段已实际恢复真实模式、偶/奇单位增益和 I2S 通道 0 开启，状态新鲜且无串口/配置队列错误。随后 3 秒真实捕获的 47,969 包、143,907 帧连续，但 DATA1/AC22 的通道 2、3 全为 −8,388,608、AC RMS=0，全部帧保留 sticky saturation。恢复和连续传输通过不等于真实阵列合格，原数据与下一步排查见[真实输入记录](reports/i2s_parity_fir_fixed_result_20261009.md#真实麦克风数据与下一步排查)。

## 测试信号与覆盖范围

pattern_id=1 的 PDM 每 1024 周期重复，稳态输出每 16 PCM 帧重复。128 路具有不同直流特征，叠加四组相位的约 3 kHz 方波成分；通道错位、相位错位和多种数据故障会导致预期值不一致。自测将 128 路逐通道校准统一为单位增益和零偏置，并把奇偶补偿按单位增益旁路；已安装的 even/odd 增益寄存器保持不变。退出后恢复正常 ROM 校准，并重新使用保留的奇偶增益。GAIN1 查询显示的是已保留的配置值；在 `SelftestMode=true` 时不能据此认为 BIST 使用了这对非单位增益。

FPGA 的同步 ROM 比较器核对每次有效 PCM 传递的数值、通道号、首尾标志和 64 位帧号；无 PCM 进展超过 100 ms 也报错。此时间包含正常 50 ms 启动等待。网络域统计完整 UDP FCS 发出事件，无发送进展超过 1 秒报错。本次自测模式内累计等待 10 秒仍未达到本地及发送目标，故障锁存超时（兼容 LED4 指示）。

报文 bit4=1 表示模拟数据，bit5=1 表示数字自测失败。自测仍使用相同 48 kHz / 24 位 / 128 路及同样带宽。UART `SelftestTxPass` 和兼容 LED3 只能证明发送端进展；必须结合上位机逐样本比较确认 PC 实际收到完整、连续数据。

## I2S 数字检查与模拟验收

原 SYS3 仍为 34 个状态字，I2S1/GAIN1 使用独立查询回帧，不改变原自测协议。I2S 可监听自测或真实模式中校准后的一个通道，并将同一样本复制到左右声道；通道和开关在 I2S 左帧边界生效。命令、查询字段和串口工具见[音频监听指南](audio_monitor.md)。

验收应区分以下证据：

| 证据 | 能证明的范围 |
|---|---|
| SYS3 本地 BIST 与 PC 黄金模型比较 | 内部 PDM、前处理、通道/帧标记及网络收到的数字 PCM 正确 |
| I2S1 新鲜、非 pending，实际选择匹配；received/verified 持续增长且 serial_errors 无新增 | 配置跨域生效，内部 I2S 串行位序与左右解码值匹配当前样本 |
| 接收计数增长且 lastPCM 非零变化 | 当前数字路径包含变化样本；单次为零不能判故障 |
| 外部焊盘波形与 PCM5102 模拟输出实测 | 物理接线、接收端供电、实际 DAC 与模拟链路工作 |

`output_frames` 与 `verified_frames` 包含静音及关闭状态，不能仅凭它们增长认定已经听到真实声音。开启期间缺样输出零并累计欠载，启动等待期间可能出现欠载；应观察稳定区间的增量。内部串行监测通过不等于外部模拟验收通过。真实阵列的增益匹配、极性、声学时延和定位性能仍需真实麦克风测量，默认单位奇偶增益不能替代标定。

MEMS 接口要求 L6/L7 与 VDD 为 1.8 V；I2S 四路位于 L5，使用 3.3 V 逻辑电平、LVCMOS33、8 mA、FAST，并与接收端共地。具体物理引脚和外部时序条件见[音频监听](audio_monitor.md)及[上板指南](board_bringup.md)。

## 兼容按键与 LED 定义

以下仅记录硬件兼容功能，现行验收采用上面的 UART 与电脑数据检查。

手册依据为《盘古MINI系列开发板硬件指导手册_V1.3》34～35 页。KEY1 按下为低，LED 输出高时亮。

| 板上器件 | FPGA 引脚 | 功能 |
|---|---|---|
| KEY0 | C22 | 全局复位，返回正常采集模式，重新装载 ROM；UART 观察域重放期望音频配置 |
| KEY1 | C23 | 每次稳定按下切换正常/自测模式；20 ms 消抖，长按只切换一次，松开后可再次触发 |
| LED0 | A20 | 音频时钟域心跳，约每 0.5 秒翻转一次；正常情况下持续闪烁 |
| LED1 | C19 | 常亮表示已选择自测，等待链路时也亮 |
| LED2 | C18 | 自测已连续校验至少 48,000 帧（6,144,000 个通道样本）且无错误 |
| LED3 | E18 | 自测时表示已完成至少 16,000 个 UDP 包发送且无发送故障；正常模式表示千兆链路就绪 |
| LED4 | A17 | 自测故障锁存：数值/顺序/调度/溢出、PHY/发送故障或 10 秒内未完成；退出再进入自测或全局复位清除 |

LED2 和 LED3 点亮后自测继续运行并继续检查；不是只发送一批数据后停止。LED4 亮时整个自测应判失败，即便其他灯仍亮。掉线会清空流并重新开始自测计数，模式保持；已经锁存的 LED4 不因短暂恢复自动清除。

## 仿真与复现

```powershell
python sim/net/run_selftest.py
python sim/audio/run_board_audio.py
python sim/verify_all.py
```

专项用例使用真实板级控制和完整数据路径，仅把 PLL/物理 RGMII/PHY 包装替换为数字模型；真实厂商原语另由全量回归覆盖。仿真保持 122.88/125 MHz 及 48 kHz 生产速率，缩短按键消抖、自测通过计数和 PDM 启动等待；预期表的稳态阶段仍丢弃 96 帧。

BIST 专项覆盖：短按抖动、长按单次触发、无链路不误报通过、全部校准重载、悬空外部 PDM、全部 128 通道比较、Ethernet/IPv4/UDP 校验、稳定阶段包率、掉线重连、内部 PDM 故障注入、错误报文标志、退出恢复外部数据、无数据超时、PHY/TX 故障、通道/帧号错误与全局复位。进入 BIST 之前，正常无网音频已经产生麦克风时钟，BIST 仍从自己的零周期重新开始，未沿用正常模式的计数。

板级音频专项另核验实际 PDM/FIR/奇偶补偿/逐通道校准到 I2S 的非零数据、全部通道数值、独立 UART 查询、运行中增益配置、BIST 保留配置但单位旁路、退出恢复，以及断网后真实音频继续。该专项的 PHY 链路为可控替身；真实 MDIO/PHY 管理器与线上 UDP 在其他完整回归层验证，不能把其数字模型当成外部 DAC 验收。

仿真原始证据在 `log/selftest/`：`vsim.log`、`faults.log`、`payloads.hex`、`host_result.json`、`result.json`。测试参考由 `lib/model/generate_selftest.py` 生成，独立 Python/C++ 定点模型比较 32,768 个 PCM 样本；ROM 和上位机预期表采用相同的经过核对的数据。板级音频仿真证据位于 `log/board_audio/`，本次完整 18/18 项结果见[系统功能报告](reports/system_verification.md)和[本版本不可变回归摘要](../log/i2s_parity/full_regression_fir_fixed_result_20261009.json)。强制厂商 UART 层核验实际技术网表，`fir_ram` 层独立检查真实历史 RAM 写入及卷积参考；证据绑定见[集成指南](integration.md)。

两级 FIR 各增加一拍写提交，奇偶补偿增加一拍分组读取；后续局部选择计数器及固定组结果切片不再增加延迟。FIR1/FIR2 为 546/1058 拍，128 路奇偶补偿为 131 拍，黄金 PCM、frame_id、抽取间隔与 BIST 门限保持不变。FIR 数据 FF 每拍刷新，但只有提交有效位才能写 RAM。实板自测绑定本次正式位流，见[交付报告](reports/i2s_parity_fir_fixed_result_20261009.md)；仿真、静态时序和内部 BIST 均不能替代外部电气、DAC 与声学验收。
