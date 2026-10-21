# 完整系统 UART 联调

[文档索引](README.md) · [上板指南](board_bringup.md) · [I2S 与奇偶补偿](audio_monitor.md) · [内部 PDM 自测](selftest.md)

更新日期：2026-10-11。当前已发布并下载版本为 **`MEMS_Array_i2s_fir8_auto_20261011`**，包含启动DC、8-lane FIR、I2S监听与独立UART配置。18层功能、唯一一轮路由、严格快/慢角时序和16:19:06 JTAG SRAM下载通过；位流SHA-256为`2947264fd95a526074212108778afc0ffbf41d2544605282bd09b0ac4f57f7ab`。新版本次A–E数字验收通过，联合结果为PASS_WITH_KNOWN_ISSUES；F真实采样连续，DATA1/ch2、3及物理未测边界保留，见[FIR8报告](reports/i2s_fir8_auto_20261011.md)、[发布](../fpga/build/MEMS_Array_i2s_fir8_auto_20261011/release.json)与[下载](../log/i2s_parity/jtag_fir8_auto_20261011/download.json)。DATA1/AC22的ch2、3、电压、DAC模拟和声学配平未验收。

本次[联合验收](../log/i2s_parity/fir8_auto_hardware_acceptance_20261011.json)为PASS_WITH_KNOWN_ISSUES，digital_acceptance_pass=true。A137案例含128/128实际选择；D128路各至少4次快照精确匹配独立oracle，并证明非unity配置下BIST旁路。C+D共504,694,272样本0内容错0缺包；E恢复real/unity/I2S0并核验27条DC完成记录、2次新鲜GAIN查询。此前retry1缺包、retry2串口启动尾片及sync缺包原FAIL均保留。本次[UDP暂存/离线解析](reports/i2s_fir8_auto_20261011.md#本次工程采集方式)通过数字验收，原lib未改；接收方式差异支持PC吞吐瓶颈方向，仍不独立证明物理链路全部电气条件合格。

首版 `MEMS_Array_i2s_parity_20261009` 已经 JTAG 下载；数字通道选择实测 **FAIL**：`@I2S=1` / `127` 返回 ErrorCode=0，但保存和实际通道均为 0，128 也未被拒绝。PDS 编译把七位通道寄存器删除为常量，修正版已改用固定字节切片和 10 位十进制算术。[首版失败反馈](../log/i2s_parity/board_audio_new_20261009/summary.json)、[首版网表负例](../log/i2s_parity/first_bit_uart_negative_control.json)、[厂商修正版网表](../log/vendor_uart/result.json)分别保留。首版网络 BIST 和真实组零增益的局部数字通过见[音频证据](audio_monitor.md#当前验证证据)，不表示首版整体通过。

`MEMS_Array_i2s_parity_uartfix_20261009` 虽通过 17/17 功能回归，仍因布线后时序 FAIL 被发布门禁拒绝，无位流；`MEMS_Array_i2s_parity_timingfix_20261009` 在加入补偿分组读流水和 FIR 写入暂存后通过 18/18 功能回归，但旧 128 个 APM 宏编号约束与新综合结果不匹配，布局 FAIL，也无位流。timingfix2 重匹配宏身份，176 个固定位置（128 个 APM、48 个历史 RAM）保持原值并被原生工具接受；首次布线尚未完成时因布线压力主动取消，无位流，最终时序结论为 `UNKNOWN_FIRST_ROUTE_INCOMPLETE`。[重匹配记录](../log/i2s_parity/timingfix_floorplan_remap_20261009.json)、[主动取消记录](../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/cancellation.json)及[取消前归档](../log/i2s_parity/timingfix2_archive_before_bank_enable_20261009.json)保留，旧构建记录见[发布依据](#仿真与发布依据)。

timingfix3 将补偿 bank 改为每个时钟读取，`group_valid` 屏蔽空闲更新；本版本技术网表核验 256 个 bank 寄存器无 CE，`busy` 仅保留标签及增益的 30 个 CE，176 个位置约束被接受。该版功能回归 18/18 PASS，但首次布线未完成时主动取消，最终时序为 `UNKNOWN_FIRST_ROUTE_INCOMPLETE`，无位流、未下载，详见[timingfix3 取消版报告](reports/i2s_parity_timingfix3_20261009.md)。

旧候选的时序失败、超时及布线取消见[版本历史](reports/version_history.md)。seed3保留局部选择与固定结果写回，补偿仍131拍；后续FIR8参数改变两级处理延迟，但UART的SYS3/I2S1/GAIN1格式和独立命令保持不变。不能用旧候选局部通过代替新版验证。

MEMS 接口设计为 L6/L7、1.8 V；I2S 接口设计为 L5、3.3 V，实际供电电压仍待测量。接线、约束与测量范围按[音频指南](audio_monitor.md#接线与接口时序)核对。旧八路版本的[发布报告](reports/clk8_18v_update.md)及旧四路实测均属于[历史版本](reports/version_history.md)，不能用作本版实板证据。

## 连接与串口控制

- COM3，115200 8N1，无流控。板载 CP210x 接 FPGA RX=B24、TX=C24，3.3 V。
- 上位机网卡保持 `192.168.10.1/24`；FPGA 为 `192.168.10.2`，UDP 目的端口 5000。
- UART 和观察器使用独立的 27 MHz 时钟，启动时将 PLL 复位保持约 20 ms。系统故障、软件复位及 PHY RXC 停振均不会阻塞串口。
- 每 250 ms 请求一行 `SYS3`，音频回应可能使发送延后；完整行保持原格式及连续序号。此前 `CLK2` 属于独立时钟诊断，不能当作完整系统状态。
- 不需要按键或 LED 组合。原物理 KEY0/KEY1 的复位/模式功能兼容保留。

| 单字符命令 | 行为 |
|---|---|
| `s` / `h` | 请求状态快照 |
| `r` | PLL/完整系统复位约 20 ms；回到真实麦克风模式；串口时基、命令计数与请求的 I2S/奇偶增益配置保留，音频域恢复后自动重放配置 |
| `t` | 向原自检控制器产生一次 100 ms 按键脉冲；消抖后切换内部 PDM 自测，两次命令间隔至少 0.2 秒 |
| `c` | 仅清除时钟历史故障，不清除 PHY/MAC 计数或当前采集错误；完整系统复位用 `r` |

这些旧命令无需换行，CR/LF 被忽略。新音频命令从 `@` 开始，以 CR 或 LF 结束。整条 `@` 命令内的字母不会触发旧单字符命令，例如非法 `@I2S=strch` 不会执行复位或切换自测。

回执表示命令被识别，动作完成以随后新鲜状态为准。自测覆盖内部 PDM 源、128 路滤波/校准、打包和发送；上位机还需独立核对收到的样本。模式切换中止旧采集会话，重载 128 路校准并启动新 epoch；旧会话 TX 错误在新会话开始时清除，当前会话错误仍锁存。

## 独立音频命令

| 以换行结束的命令 | 行为 / 独立回应 |
|---|---|
| `@I2S=0` 至 `@I2S=127` | 选择校准后 PCM 通道并启用监听；回应 `I2S1` |
| `@I2S=OFF` | 静音，保留所选通道，SCK/BCK/LRCK 继续运行；回应 `I2S1` |
| `@I2S?` | 查询请求值和真实音频域状态；回应 `I2S1` |
| `@GAIN=EEEEEE,OOOOOO` | 设置所有偶数/奇数通道的补偿增益；回应 `GAIN1` |
| `@GAIN?` | 查询请求增益、实际配置寄存器和音频计数；回应 `GAIN1` |

增益为六位十六进制、非负 Q2.22，合法范围 `000000`～`7FFFFF`；`400000`=1，`200000`=0.5，`300000`=0.75。默认启用通道 0，奇偶增益均为 1。配置在 PCM/I2S 帧边界生效，收到回应后继续查询，直到 `Fresh=true`、`Pending=false` 且实际值与请求一致。

`I2S1` 和 `GAIN1` 各含 **14 个大写八位十六进制字**，以单个空格分隔并以 CRLF 结束；长度分别为 132、133 字节。它们与原 312 字节 `SYS3` 在同一 TX 引脚上按整行仲裁，SYS3 字数、字段和旧命令计数不变。音频回应使用独立序号。

| 音频字索引 | 含义 |
|---|---|
| 0 | 独立音频回应序号，模 2^32 回绕 |
| 1 | bit0=`Fresh`，bit1=`Pending`，bit2=`AudioResetReleased`；bit8..15=错误码；bit16..31=回应队列溢出计数 |
| 2 / 3 | 请求 / 实际 I2S 状态：bit7=启用，bit0..6=通道号 |
| 4 / 5 | 请求偶数 / 奇数增益，低 24 位 Q2.22 |
| 6 / 7 | 音频域实际偶数 / 奇数配置寄存器，低 24 位 Q2.22 |
| 8 / 9 / 10 | 所选通道收到的 PCM 样本 / I2S 输出帧 / 欠载帧计数 |
| 11 | 最近输出的 PCM，低 24 位有符号数 |
| 12 / 13 | 独立串行监测器验证帧数 / 串行错误数 |

错误码 0=合法命令，1=语法错误，2=越界。回应队列深度为 8；满队列时拒绝配置并累计溢出。主机应一次发送一条命令、等待回应后再发下一条。音频时钟停止时 UART 仍可回应，`Fresh=false`、`Pending=true`；此时实际字段没有当前状态含义，主机解析器返回空值。bit2 只说明复位释放，时钟是否能响应须结合新鲜位和计数进展判断。

`GAIN1` 的 actual 表示音频域已经生效的**配置寄存器值**。内部 PDM 自测期间实际处理旁路奇偶补偿并使用 unity；判定该模式须同时读取 SYS3 的 `SelftestMode`，不能从 GAIN1 非 unity 配置推断 BIST 样本被缩放。

在项目根目录使用配置工具。每次调用只打开一次 COM3，在同一会话中完成设置及后续查询后关闭；只有请求值、保存值、实际值一致且 `Fresh=true`、`Pending=false`、音频复位已释放、ErrorCode=0、QueueOverflows=0，才报告配置成功。`Query` 返回 I2S/增益两种状态，保留 pending/stale 事实。勿与其他串口工具同时运行：

```powershell
.\lib\host\audio_uart.ps1 -Port COM3 -Action Query
.\lib\host\audio_uart.ps1 -Port COM3 -Action Select -Channel 127
.\lib\host\audio_uart.ps1 -Port COM3 -Action Off
.\lib\host\audio_uart.ps1 -Port COM3 -Action Gain -EvenGain 200000 -OddGain 300000
.\lib\host\audio_uart.ps1 -Port COM3 -Action Gain -EvenGain 400000 -OddGain 400000
.\lib\host\audio_uart.ps1 -Port COM3 -Action Select -Channel 127 -LogPath log/i2s_parity/select127_uart_run01.log
```

`-LogPath` 可选，记录完整 TX/RX 文本且拒绝覆盖已有文件；异常同时附带最近收发记录。旧工具曾有一次退出失败且未保存原始串口记录，具体原因未证实；不能把随后未经配置确认的 PCM 捕获算作通过。当前工具已用 11 个无串口 mock 正/负例验证，保存值或实际值与用户请求不符时必须失败。

`capture_system_uart.ps1` 同时识别三种帧，把音频回应另存为 `audio_records.json`，不将它们计为 SYS3 格式错误或序号缺口。I2S、补偿、物理预算及校准流程详见[音频指南](audio_monitor.md)。

## 实板逐级验收

当前FIR8本次A–E数字通过、F连续且ch2/3故障保留，详见[本版报告](reports/i2s_fir8_auto_20261011.md)。下表仅是旧B的历史分级结果，原始目录为`log/i2s_parity/fir_fixed_result_hw_20261009/`，不能作为新版通过依据。每次复测使用新目录，保存位流SHA、实际UART日志、电脑收包和逐样本校验，分别记录FPGA发送进展与电脑接收结果。

| 旧B阶段 | 历史确认结果 |
|---|---|
| A：监听与配置 | 137 案例 PASS；0～127 每路两次快照的请求/保存/实际值一致，fresh、无 pending，PCM 接收/I2S 输出/独立验证计数进展；OFF、非法命令和复位重放通过 |
| B：真实奇偶组归零 | 偶组 48,090、奇组 143,736 个稳定帧；各组 64 路全部样本严格为零，另一组 64 路都有非零样本；无捕获错误，unity 已恢复。ch3/ch2 rails 仍列 `KNOWN_ISSUE` |
| C：PHY→ARP→UDP BIST | PHY `001CC916`、ACK/link/peer 正常；595,272 帧、76,194,816 个样本逐位匹配独立 oracle，无错误标志、连续性或主机采集错误 |
| D：I2S 内容及旁路 | 128 路各 4 次快照、至少 2 个不同值，精确匹配该通道 16 值 oracle；GAIN1 保留 0.5/0.75，而 BIST 内容使用 unity；稳态欠载增量为零。并行 UDP 比较 3,359,991 帧、430,078,848 个样本通过 |
| E：退出恢复 | 实际 `r` 回真实模式，unity 和初始通道 0/启用恢复；两次 GAIN 查询及 I2S 查询新鲜且已生效，UART 连续、UDP 计数递增；sticky CLIP 保留 |
| F：恢复后真实采样 | 3 秒收到 143,907 帧、47,969 包，连续且无主机采集错误；通道 2/3 每个样本均 −8,388,608、AC RMS=0、rail=100%，全部帧饱和。结论为 `PASS_WITH_KNOWN_ISSUES`，不是幅值校准 |

E串口采集器单独PASS只表示配置/串口检查通过；联合验收另检查完整SYS3健康和UDP计数，F再验证真实UDP数据。旧B的[审证索引](../log/i2s_parity/fir_fixed_result_hardware_independent_index_20261009.json)及[87文件哈希](../log/i2s_parity/fir_fixed_result_hardware_raw_hashes_20261009.json)保留历史。内部串行监测与BIST不证明DAC模拟、供电或声学幅值，计数也不是绝对PCM相位。

修正版下载后，先在单一串口会话验证全部通道、OFF、增益及复位重放：

```powershell
.\lib\host\selftest_audio_board.ps1 -Port COM3 -AllChannels -OutputDirectory log/i2s_parity/board_audio_all_channels_run01
```

默认未指定 `-AllChannels` 时只覆盖 0/1/127。全通道选项逐一检查 0～127，每次均核对真实快照与请求值一致、pending 清除及 PCM 接收/I2S 输出/独立验证帧计数进展；最后恢复原通道/使能并恢复 unity 增益。目录须未使用；完整步骤及限制见[数字实板自测](audio_monitor.md#数字实板自测与-dac-验收)。内部串行监测无法证明 DAC 模拟输出或声学幅值。

下载新位流后可先运行只读采集：

```powershell
.\lib\host\capture_system_uart.ps1 -Port COM3 -Seconds 15
```

自动复位并进入内部 PDM 自测：

```powershell
.\lib\host\capture_system_uart.ps1 -Port COM3 -Seconds 30 -SelfTest
```

自动脚本只在收到有效 `SYS3` 后发送命令：约 1 秒时 `r`；至少 4 秒，且时钟恢复、快照新鲜、校准完成、PHY 链路建立及 ARP 对端有效后才发送 `t`。内部 PDM 自测仍等待 ARP，避免测试起始帧溢出。**真实模式的前处理与 I2S 可在无网时运行**；网络发送仍等待链路和 ARP，从完整新帧开始入队。结束后保持自测模式，便于继续捕获网络数据。日志目录默认 `log/system_uart/capture_时间/`，包含原始字符、SYS3/音频解析记录和诊断摘要；退出会关闭 COM3。使用时关闭其他串口助手。

| 阶段 | 通过依据 | 未通过时重点查看 |
|---|---|---|
| 时钟/复位 | `ClocksHealthy=true`，稳态时钟历史无新异常 | lock/reset/frequency 掩码；采样域是否新鲜 |
| PHY/MDIO | `PhyId=001CC916`，`PhyReady=true`，`LinkUp=true`；PHYSR 低位满足 `(value & 003C)==002C` | MDIO 最近事务、ACK、扫描地址、失败 state/step/reg/data、重试计数及 PHY 复位 |
| ARP | `ArpRequestsSent` 增加；有效 ARP 到达后 `ArpAccepted` 增加、`PeerValid=true`，MAC 对应电脑网卡 | UART RX 原始帧计数与电脑二层抓包；区分无发送、无接收与解析拒绝 |
| UDP | FPGA `UdpSent` 持续增加，电脑 UDP 5000 实际收到包 | FPGA 计数只表示完成 GMII 发送；电脑无包时继续检查 RGMII/PHY/主机接收 |
| 自测数据 | FPGA 两个 BIST PASS；电脑收到连续、无错误标志且逐位匹配的 128 路样本 | 队列丢包、epoch/帧号缺口、滤波/校准和包内标志 |

自动摘要 `Stage` 按代码检查顺序给出首个未满足条件。`Acquiring` 表示网络流已释放；等待 ARP 时可能显示 `ACQUISITION_NOT_READY`，此时真实模式的 I2S 仍可工作。结合 `LinkUp`、`PeerValid`、I2S 的 `ReceivedSamples` / `VerifiedFrames` 分别定位网络与监听，不能仅按摘要标签认定前处理停止。

PHY 扫描不存在的地址会产生正常的读无 ACK，不能仅凭 `MdioReadNoAcks>0` 判失败。结合 `PhyReady`、配置步骤、失败快照及重试次数判断。写事务没有 Clause22 ACK，`MdioAck` 仅在 `MdioRead=true` 时有效。PHY 历史 `fault` 在自动重试后仍保留，软件复位才清除。

先等待 UART 自测通过，再在另一终端接收 5 秒 PCM。下面覆盖稳定区间；启动/模式切换另按后文验证：

```powershell
python lib/host/receive_pcm.py --bind 192.168.10.1 --seconds 5 --output log/system_uart/board_capture/pcm
python lib/host/verify_selftest.py --capture log/system_uart/board_capture/pcm --min-frames 48000 --output log/system_uart/board_capture/pcm_check.json
```

输出前缀必须未被使用。捕获脚本保存 PCM、逐帧元数据及缺帧/队列统计；5 秒数据约 92 MB。电脑端逐位比较通过后，才可称内部 PDM 到上位机的链路通过。本版不包含上位机 SRP-PHAT 算法，数字自测也不证明真实麦克风的声学性能。

如需二层证据，可复用 `log/hardware_debug/capture_npcap.py`，指定当前 FPGA 网卡的 Npcap 设备名，限定捕获 ARP 和 `192.168.10.2`。同时保存串口、PCAP 和 PCM 的时间与位流 SHA-256。无需修改防火墙来验证 PLL 或 MDIO。

如需验证模式切换首包连续性，应先启动使用新前缀的电脑接收器，再发送 `t`。内部 PDM 自测的新 epoch 从第 96 帧开始；真实模式若在等待 ARP 时已运行，联网首帧可能更晚，应检查从完整帧开始及后续连续性。验证复位启动时，把 `r` 作为一次独立测试，并使用新的捕获文件，不能合并复位前后的同名 epoch。单独捕获稳定运行的几秒数据无法排除先前发生的启动丢帧。真实输入 `Clipped=true` 或 UDP flags bit0=1 时，先检查输入和幅度；不要将这些包当作正常音频。

## SYS3 协议

每行 312 字节，ASCII：`SYS3 `，随后 34 个大写八位十六进制字，以单个空格分隔，最后 CRLF。索引从 0 开始。计数器模 2^32 回绕；命令和串口错误计数模 2^16 回绕。

| 字索引 | 含义 |
|---|---|
| 0 / 1 | 串口帧号 / 独立观察域毫秒计时 |
| 2 | bit0..2=96/audio/eth PLL LOCK；bit3..5=common/audio/eth reset released；bit6..10=原控制器状态；bit11..14=raw125/96/audio/eth 频率合格；bit15..18=时钟历史故障；bit19..22=当前故障；bit23..26=历史检查已启用；bit27=系统复位请求 |
| 3 / 4 | 低/高 16 位依次为 raw125、96、audio、eth 的计数差；生产参数乘 0.1024 得 MHz 相对估计 |
| 5 | bit0..15=命令数；bit16..23=最近命令 ASCII |
| 6 | 低 16 位 UART RX 停止位错误；高 16 位未知命令数 |
| 7 | bit0..2=audio/eth/rx 快照新鲜；bit4..6=对应快照应答等待中 |
| 8 | bit0=started，1=acquiring，2=run，3=selftest_mode，4=overflow，5=processing_error，6=clipped，7=local pass，8=local fail，9=audio reset released，10=calibration_done，11=loaded_mode，12=直流补偿启用，13=直流估计审核结束，14=至少一路直流估计被拒绝，19..23=原控制器状态 |
| 9 / 10 / 11 | 丢弃采样帧数 / 已握手 PCM 样本数 / 最近 PCM 帧号低 32 位 |
| 12 | bit0..3=PHY state；4..8=cfg_step；9..13=PHY 地址；14=ready；15=link_up；16=历史 fault；17=PHY reset released |
| 13 | 高 16 位最近有 ACK 的 ID1，低 16 位 ID2；扫描中应结合地址与 ready 判断 |
| 14 | 最近完成 MDIO 的 state[3:0]、step[8:4]、reg[13:9]、addr[18:14]、ACK[19]、read[20] |
| 15 | 高 16 位最近事务写数据，低 16 位读数据；按 word14 的 read 位解释 |
| 16 / 17 / 18 | 完成 MDIO 事务数 / 读无 ACK 次数 / PHY 故障重试次数 |
| 19 | 最近失败快照：state[31:28]、step[27:23]、read[22]、ACK[21]、reg[20:16]、读数据[15:0]；跨自动重试保留 |
| 20 | 最近有 ACK 的 PHYSR 读回值 |
| 21 | bit0=tx_en，1=MAC 物理链路，2=peer_valid，3=packet_full，4=tx_error，5=reply_pending，6=draining，7..9=MAC state，10..11=帧类型；12=framing_error，13=TX BIST pass，14=TX BIST fail，15=eth_stream_rst_n |
| 22 / 23 / 24 | 完成的 ARP request TX / ARP reply TX / MAC 接受的有效 ARP 数 |
| 25 / 26 / 27 | 完成的 UDP TX 数 / 全部 Ethernet TX 数 / stream epoch |
| 28 / 29 | 已解析对端 MAC 的低 32 / 高 16 位 |
| 30 / 31 / 32 / 33 | RX 帧数 / 出现 RX_ER 的帧数 / RX_DV 字节数（含前导码/FCS）/ RX 域周期数 |

新源码的 bit12..14 分别解析为 `DcCorrectionEnabled`、`DcEstimationFinished`、`DcAnyChannelRejected`。这些位扩展原 SYS3 的 word8，字数、行长及独立 I2S1/GAIN1 回帧保持不变；旧已发布位流没有这些诊断位。真实模式的估计审核结束不表示全部通道正常，需同时检查拒绝位和 `Clipped`。BIST 根据 `SelftestMode` 判断旁路，不能仅凭 bit12 推断正在扣除直流；`@GAIN?` 查询的仍是增益配置，不包含每通道直流值。

PHY 状态编号：0 复位、1 等待、2/3 读 ID1 请求/等待、4/5 读 ID2、6 下一个地址、7/8 配置请求/等待、9 轮询间隔、10/11 PHYSR 轮询、12 故障重试等待。配置步骤见 `rtl/net/rtl8211f_manager.sv`。

时钟故障掩码：bit0=公共/局部复位，bit1=96 MHz，bit2=音频，bit3=以太网。初始启动或主动复位期间当前故障非零是预期，历史故障在曾正常后才启用。

每条串口行在发送前冻结。audio、eth（包含 PHY 和 MAC）、rx 各自通过握手取得原时钟域内一致的快照，各域之间存在少量采样时差。新鲜位为 0 时相应字段仅为上次快照，不能当作当前状态。接收时钟停止不会无限等待；迟到的应答也不会被标成下一次请求的新鲜数据。

RX 帧计数只表示接收到 RX_DV，不保证一般帧的 FCS 正确；`ArpAccepted` 则经过原 ARP 解析器的格式、目标地址和 FCS 校验。相对频率计数无法测量绝对晶振误差、占空比或抖动。

## 仿真与发布依据

完整回归入口为`python sim/verify_all.py`。[seed3不可变回归](../log/i2s_parity/full_regression_dc_roundsat_20261009.json)与[FIR8回归](../log/i2s_parity/full_regression_fir8_auto_20261011.json)各18层通过，分别绑定104项输入和22份向量。FIR8已有自己的严格发布和SRAM下载；本次spool A–E数字通过、F143,589帧连续，[联合验收](../log/i2s_parity/fir8_auto_hardware_acceptance_20261011.json)PASS_WITH_KNOWN_ISSUES；原缺包和串口启动尾片FAIL保留。首attempt的旧runner名称匹配拒绝在打开COM前exit2，归档`fir8_auto_hw_20261011_outer_invocation`；精确加入新名字的副本未改验收判据。顶层103端口、SYS3 34字/312字节和音频命令保持不变。

| 候选 / 记录 | 已确认状态 |
|---|---|
| [uartfix 构建](../fpga/build/MEMS_Array_i2s_parity_uartfix_20261009/manifest.json) | [17/17 功能回归 PASS](../log/i2s_parity/full_regression_uartfix_20261009.json)，布线后时序 FAIL，发布门禁拒绝生成位流；未下载 |
| [timingfix 构建](../fpga/build/MEMS_Array_i2s_parity_timingfix_20261009/manifest.json) | 18/18 功能回归 PASS，旧 APM 宏编号约束导致布局 FAIL；无位流、未下载 |
| [timingfix2 构建](../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/manifest.json) | 176 个位置约束被原生工具接受；首次布线未完成时[主动取消](../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/cancellation.json)，最终时序未知，无位流、未下载 |
| [timingfix3 取消版](reports/i2s_parity_timingfix3_20261009.md) | 18/18 功能回归、技术网表与 176 项宏位置审计 PASS；首次布线未完成时主动取消，最终时序未知，无位流、未下载 |
| [timingfix4 历史候选](../fpga/build/MEMS_Array_i2s_parity_timingfix4_20261009/manifest.json) | 18/18 功能回归 PASS；完整构建最终 FAIL，无发布位流 |
| [seed3历史基线](reports/i2s_parity_dc_roundsat_seed3_20261011.md) | 16-lane严格发布、JTAG与A–F数字通过；DATA1、电压、DAC及声学边界保留 |
| [FIR8已下载版](reports/i2s_fir8_auto_20261011.md) | 18层、唯一一轮路由、严格发布与16:19:06 JTAG通过；本次spool A–E数字通过，联合PASS_WITH_KNOWN_ISSUES；retry1/retry2/sync原FAIL保留，物理项目未验收 |
| [fir_fixed_result旧B](reports/i2s_parity_fir_fixed_result_20261009.md) | 历史18层、物理发布、JTAG与A–F记录保留，不代替启动DC或FIR8验证 |

[FIR8真实RAM定向](../log/i2s_parity/fir8_directed_ram_20261011.json)六配置11,435,616项通过，覆盖真实地址/内容/读数据、回绕、独立卷积、末写同拍接收、复位及overrun。8-lane两级延迟1090/2114拍；seed3的16-lane基线为546/1058拍，补偿两者均131拍。两版通过范围分别由自己的回归和物理记录证明；20,614项旧B补偿检查属于历史，不包含启动DC。

UART 集成仿真使用完整顶层、真实 PHY 管理器/MDIO 控制器、引脚级 PHY 模型、ARP 应答及 UDP 线上 FCS 检查，覆盖自测、发送中切换、RX 停钟、MDIO 无 ACK、自动恢复和软件复位。音频 UART 独立仿真覆盖全部数字通道、128/999 拒绝、OFF、背压、停音频钟、短复位重放与 SYS3 整帧仲裁，278,636 项检查通过。[厂商 UART 技术网表验证](../log/vendor_uart/result.json)确认七位通道寄存器保留，并通过 128 通道、55,197 项检查；其范围到 dev_map，不含布线或 SDF，完整板级物理检查仍须在发布时通过。

集成测试的 PLL/DDR 使用数字替身；真实厂商原语由完整回归中的独立项目验证。上位机解析器直接解析 RTL 输出，核对三种串口帧。首版 72,185,856 个网络 BIST 样本与组零测试作为历史局部结果保留，本版另用新位流、新执行记录完成 A–F。饱和标志及通道 2/3 满量程故障仍保留，`physical_amplitude_calibrated=false`；详见[音频证据及原始记录](audio_monitor.md#当前验证证据)。当前 unity 是默认数字增益，不能代表声学校准通过。
