# 内部 PDM 自测与上位机验收

[文档索引](README.md) · [UART 联调](system_uart_debug.md) · [上板指南](board_bringup.md)

适用版本：**`MEMS_Array_uart_clk8_18v_spread3_long`**。当前工程发布 PASS，本版实板测试待执行。内部产生确定性 PDM，经过双相采集、滤波、校准、打包与千兆 UDP 发送；不连接麦克风也可验证数字链路，不能检测外部供电、接线、时钟负载或声学性能。

## 1. 准备

按[上板指南](board_bringup.md)确认供电、下载当前位流。电脑网卡设为 `192.168.10.1/24`，连接千兆 PHY0，允许 UDP 5000。COM3 使用 115200 8N1、无流控，并关闭其他占用串口的程序。

## 2. 通过 UART 进入自测

在工程根目录执行：

```powershell
.\lib\host\capture_system_uart.ps1 -Port COM3 -Seconds 30 -SelfTest
```

脚本先确认 SYS3，再发 `r` 复位；等待时钟、校准、PHY 与 ARP 就绪后发 `t` 切换。结束后保持自测，便于继续接收数据。不要再盲发 `t`，因为它会切换回真实输入。

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

## 4. 恢复真实输入

确认当前 `SelftestMode=true` 后发送一次 `t`：

```powershell
.\lib\host\capture_system_uart.ps1 -Port COM3 -Seconds 5 -Command t
```

等待新鲜状态中 `SelftestMode=false`。系统停止并清空旧流，重载正常校准 ROM，启动新 epoch。未接阵列时真实输入没有声学意义；自测包 bit4=1，不得送入定位算法。

## 测试信号与覆盖范围


pattern_id=1 的 PDM 每 1024 周期重复，稳态输出每 16 PCM 帧重复。128 路具有不同直流特征，叠加四组相位的约 3 kHz 方波成分；通道错位、相位错位和多种数据故障会导致预期值不一致。自测使用单位增益和零偏置，退出后恢复正常 ROM 配置。

FPGA 的同步 ROM 比较器核对每次有效 PCM 传递的数值、通道号、首尾标志和 64 位帧号；无 PCM 进展超过 100 ms 也报错。此时间包含正常 50 ms 启动等待。网络域统计完整 UDP FCS 发出事件，无发送进展超过 1 秒报错。本次自测模式内累计等待 10 秒仍未达到本地及发送目标，故障锁存超时（兼容 LED4 指示）。

报文 bit4=1 表示模拟数据，bit5=1 表示数字自测失败。自测仍使用相同 48 kHz / 24 位 / 128 路及同样带宽。UART `SelftestTxPass` 和兼容 LED3 只能证明发送端进展；必须结合上位机逐样本比较确认 PC 实际收到完整、连续数据。


## 兼容按键与 LED 定义

以下仅记录硬件兼容功能，现行验收采用上面的 UART 与电脑数据检查。

手册依据为《盘古MINI系列开发板硬件指导手册_V1.3》34～35 页。KEY1 按下为低，LED 输出高时亮。

| 板上器件 | FPGA 引脚 | 功能 |
|---|---|---|
| KEY0 | C22 | 全局复位，返回正常采集模式 |
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
python sim/verify_all.py
```

专项用例使用真实板级控制和完整数据路径，仅把 PLL/物理 RGMII/PHY 包装替换为数字模型；真实厂商原语另由全量回归覆盖。仿真保持 122.88/125 MHz 及 48 kHz 生产速率，缩短按键消抖、自测通过计数和 PDM 启动等待；预期表的稳态阶段仍丢弃 96 帧。

覆盖：短按抖动、长按单次触发、无链路不误报通过、全部校准重载、悬空外部 PDM、全部 128 通道比较、Ethernet/IPv4/UDP 校验、稳定阶段包率、掉线重连、内部 PDM 故障注入、错误报文标志、退出恢复外部数据、无数据超时、PHY/TX 故障、通道/帧号错误与全局复位。

原始证据在 `log/selftest/`：`vsim.log`、`faults.log`、`payloads.hex`、`host_result.json`、`result.json`。测试参考由 `lib/model/generate_selftest.py` 生成，独立 Python/C++ 定点模型比较 32,768 个 PCM 样本；ROM 和上位机预期表采用相同的经过核对的数据。
