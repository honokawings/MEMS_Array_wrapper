# I2S 监听与奇偶通道补偿

[文档索引](README.md) · [UART 联调](system_uart_debug.md) · [完整引脚映射](../README.md#mems-麦克风引脚映射) · [采集工具](host_capture.md)

更新日期：2026-10-11。当前已发布并下载版本为 **`MEMS_Array_i2s_fir8_auto_20261011`**：18层功能回归、唯一一轮原生路由与严格快/慢角时序通过，16:18:08发布授权、16:19:06经JTAG SRAM下载成功，未写Flash。位流SHA-256为`2947264fd95a526074212108778afc0ffbf41d2544605282bd09b0ac4f57f7ab`。本次A–E数字验收通过，联合结果PASS_WITH_KNOWN_ISSUES；见[FIR8报告](reports/i2s_fir8_auto_20261011.md)、[发布门禁](../fpga/build/MEMS_Array_i2s_fir8_auto_20261011/release.json)和[下载记录](../log/i2s_parity/jtag_fir8_auto_20261011/download.json)。

前一[seed3基线](reports/i2s_parity_dc_roundsat_seed3_20261011.md)已验证128路监听、真实组零、网络/I2S BIST旁路及退出恢复；FIR8已有自己的[联合验收](../log/i2s_parity/fir8_auto_hardware_acceptance_20261011.json)，128路选择和I2S独立内容均通过；不沿用历史结果。**DATA1（AC22）的通道2/3故障、实际供电电压、PCM5102模拟输出和64对声学幅值仍未验收。默认unity是功能配置，不是测得的声学校准。**

首版 `MEMS_Array_i2s_parity_20261009` 已生成并经 JTAG 下载，但数字通道命令实测失败：选择 1、127 后请求值和实际值仍为 0，128 也未被拒绝。PDS 编译将通道号的七个寄存器错误优化为常量 0；首版物理发布 PASS 不能代替这项功能验收。修正版采用固定字节切片、明确 10 位算术解析十进制通道号，厂商技术网表保留全部七位寄存器并通过数字命令测试。[首版实测失败](../log/i2s_parity/board_audio_new_20261009/summary.json)、[首版网表负例](../log/i2s_parity/first_bit_uart_negative_control.json)、[修正版厂商网表验证](../log/vendor_uart/result.json)

后续候选的历史结论分别保留：`MEMS_Array_i2s_parity_uartfix_20261009` 功能回归 17/17 PASS，但布线后时序未通过，发布门禁拒绝生成位流；`MEMS_Array_i2s_parity_timingfix_20261009` 增加奇偶补偿分组读流水及 FIR 写入暂存后，功能回归 18/18 PASS，但旧 128 个 APM 宏编号与新综合结果不匹配，布局失败，也没有位流。timingfix2 重匹配宏身份，保持原 176 个位置（128 个 APM、48 个历史 RAM），原生工具接受全部位置约束；首次布线尚未完成时，因布线压力主动取消，未生成位流，最终时序结论为 `UNKNOWN_FIRST_ROUTE_INCOMPLETE`。[宏身份重匹配证据](../log/i2s_parity/timingfix_floorplan_remap_20261009.json)、[主动取消记录](../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/cancellation.json)及[取消前归档](../log/i2s_parity/timingfix2_archive_before_bank_enable_20261009.json)保留。

timingfix3 将补偿器的 `bank_sample` 改为每个时钟读取，空闲更新由 `group_valid` 屏蔽；新技术网表确认 256 个 bank 寄存器保留且无 CE，`busy` 仅保留标签及增益的 30 个 CE，176 个位置约束被接受。该版功能回归 18/18 PASS，但首次布线尚未完成时主动取消，最终时序为 `UNKNOWN_FIRST_ROUTE_INCOMPLETE`，无位流、未下载。[timingfix3 取消版报告](reports/i2s_parity_timingfix3_20261009.md)保存本版本审计、原始布线和取消前完整归档，不能将其当作最终时序失败或通过。

旧候选的超时、取消和时序失败保留在[版本历史](reports/version_history.md)，不能据未完成布线推断最终时序。已下载seed3保留局部选择与固定组结果写入，加入启动DC和并行FIR舍入/饱和；补偿仍131拍，帧号和UART协议不变。

FIR8每级16→8条乘加流水，总APM132→68（−48.5%）；采样率和128通道不变，共同处理延迟增加约13.02µs。布线、时序及发布身份见[FIR8报告](reports/i2s_fir8_auto_20261011.md)；本次C+D共504,694,272个样本0错误0缺包；此前捕获失败仍保留，不用旧seed3结果代替新版通过。

下方[验证证据](#当前验证证据)分别列出本版结果和历史结果；首版局部数字通过不抵消其通道选择失败。更早的 `MEMS_Array_uart_clk8_18v_spread3_long` 发布结果仅用于历史追溯。

## 当前源码新增的启动直流补偿

本节启动DC已包含于前一seed3和当前FIR8。seed3实测SYS3启用、审核结束、有拒绝均true，详见[历史基线报告](reports/i2s_parity_dc_roundsat_seed3_20261011.md)；这不说明全部通道正常。FIR8已完成自己的[18层回归](../log/i2s_parity/full_regression_fir8_auto_20261011.json)、严格发布和[实板验收](../log/i2s_parity/fir8_auto_hardware_acceptance_20261011.json)；E有27条真实DC完成记录、2次新鲜unity GAIN查询及I2S0 ON，any-rejected与stickyCLIP保留。初版DC负时序FAIL与roundsat seed2超时FAIL保留在[版本历史](reports/version_history.md)。

MEMS 手册的 LR=GND/VDD 典型直流水平为 −80/−40 dBFS，属于对数幅度，不能直接作为负的数字偏置，也不能据此给交流信号设置 100 倍组增益。[手册第 9 页](IM72D128V01XTMA1.pdf)

新板级默认在滤波稳定的 96 帧之后，逐通道累计 4096 帧均值并审核，然后冻结直流补偿值。该方法利用手册所述的稳定直流特性，避免假定未明确的偏置符号和 dBFS 换算基准。启动时保持声场稳定，优先安静环境；估计期间输出静音。饱和、过大或半窗不稳定的均值被拒绝，该路继续保留原故障表现。SYS3 的 `DcEstimationFinished=true` 只说明审核结束，应同时检查 `DcAnyChannelRejected` 和输入饱和状态。

单位组增益仍执行直流扣除；`@GAIN=400000,400000` 不关闭这项功能。直流先扣除，之后执行奇偶组增益，再减去 ROM 的后级偏置并乘逐通道增益。更改组增益或选择监听通道不会重新估计直流；复位、停用前端及退出 BIST 会重新训练，真实模式掉网保持已冻结值。内部 BIST 旁路直流扣除并保持原黄金样本。手册名义交流增益为 1，个体声学幅值配平仍须另行测量；去直流不等于灵敏度标定。参数、拒绝条件和定点算术见[算法规格](algorithm_spec.md)。

## 信号路径与运行方式

```text
64 根共享 PDM DATA → 128 通道双相采集 → CIC /8 → FIR /4 → FIR /2
  → 每通道启动直流扣除 → 奇偶组增益 → 原逐通道增益/后级偏置校准
  → 48 kHz / 24 bit PCM → 选择通道 → 标准 I2S → PCM5102
                         └→ 网络 FIFO → ARP / UDP
```

监听取**完成前处理及逐通道校准后的 PCM**。所选单声道同时复制到 I2S 左、右声道；它不是监听一对麦克风。真实麦克风模式下，前处理和监听独立于网络，未接网线、链路未建立或 ARP 未完成时仍能输出音频；UDP 则等链路/ARP 就绪后从完整新帧开始发送。

默认监听通道 0，奇偶补偿增益均为 1。配置在帧边界更新，切换时丢弃旧通道缓存；当前帧保持完整，随后使用新通道的新样本。`OFF` 保留通道号、输出零数据，时钟继续运行。启用状态下缺少新样本也输出零，并累计 `Underruns`，不会重复上一帧。上电、复位、模式切换和通道切换附近的欠载需结合时间及计数增长判断。

启动先输出 3.072 MHz PDM 时钟，等待 153,600 个 PDM 周期，即 **50 ms**，再开始有效采集；滤波器另丢弃 **96 个 48 kHz 帧（2 ms）**。新板级真实模式再估计 **4096 帧（85.33 ms）**直流，第 4192 帧开始输出，合计约 137.33 ms，另有校准加载与流水延迟。BIST 和默认禁用估计的便携内核仍从第 96 帧输出。I2S 时钟在音频域复位释放后运行，尚无 PCM 时发送零。

内部 PDM BIST 使用固定参考模型，需要网络链路及 ARP；该模式实际旁路奇偶补偿并使用 unity，退出时恢复用户校准及补偿配置。`GAIN1` 的 active 为实际配置寄存器值，是否旁路必须结合 SYS3 `SelftestMode`。仅观察 GAIN1 不足以判断 BIST 数据的乘法系数。

## 接线与接口时序

完整连接器方向及 MEMS 信号以[README 原始映射](../README.md#mems-麦克风引脚映射)为准。I2S 四脚位于 J10 的 Bank L5，设计使用 **3.3 V、LVCMOS33、8 mA、FAST**；麦克风 CLK/DATA 位于 Bank L6/L7，设计使用 **1.8 V、LVCMOS18**。这些是设计与约束值，实际 Bank 跳线/VCCIO、MEMS VDD 和 DAC 端电压仍需测量，不能据数字测试通过认定供电已验收。两类接口按各自电压接线并共地。

| FPGA 端口 | README 信号 | 封装引脚 | 接 PCM5102 | 频率 |
|---|---|---|---|---:|
| `i2s_sck` | SCK | R21 | SCK / MCLK | 12.288 MHz，256×Fs |
| `i2s_bck` | BCK | N19 | BCK | 3.072 MHz，64×Fs |
| `i2s_din` | DIN | M25 | DIN | 24 位有效数据 |
| `i2s_lrck` | LRCK | T25 | LRCK / WS | 48 kHz |

采用标准 I2S：每声道 32 个 BCK、24 位有符号数据 MSB 优先、低 8 位补零，LRCK 低为左声道，高为右声道，MSB 在 LRCK 切换后延迟一个 BCK。DIN/LRCK 只在 BCK 下降沿更新，DAC 在上升沿采样。PCM5102 硬件设置应选择 `FMT=0`（I2S）、`XSMT=1`（解除静音）、`DEMP=0`；模块电源按模块原理图核对，芯片的 3.3 V 供电与模块 VIN 名称不能混用。[TI PCM5102 手册，第 3、13 页](https://www.ti.com/lit/ds/symlink/pcm5102.pdf)

物理预算独立于 RTL 位序仿真：实际布线的慢角/快角网表与 SDF 都需检查输出寄存器、时钟分支和输出缓冲。项目约束 SCK/BCK 内部输出路径≤4 ns、DIN/LRCK≤20 ns，并以 **20 ns 外部相对延迟/边沿不确定度预算**及 0.300 ns 时钟不确定度核算；最终要求 DAC 端 DIN/LRCK 对 BCK 的建立/保持均≥20 ns，严于芯片 8 ns 最低要求。[TI PCM5102 时序要求](https://www.ti.com/lit/ds/symlink/pcm5102.pdf#page=13)

外部20ns是接线契约，仍需在PCM5102引脚处实测偏斜、边沿和负载，软件预算PASS不代替电气验收。检查器为`fpga/scripts/check_i2s_budget.py`；当前FIR8快/慢角预算随[自己的发布门禁](../fpga/build/MEMS_Array_i2s_fir8_auto_20261011/release.json)通过，外部测量仍待完成。

## UART 操作与回帧

COM3，115200 8N1，无流控。以下命令在项目根目录运行。每次调用在一个串口会话中完成配置及后续查询，只有请求值、保存值和实际值一致，且 fresh=1、pending=0、音频复位已释放、ErrorCode=0、QueueOverflows=0，才报告配置成功。`Query` 显示 I2S/增益两种回应及 pending/stale 事实，不强行声称配置已生效。

```powershell
.\lib\host\audio_uart.ps1 -Port COM3 -Action Query
.\lib\host\audio_uart.ps1 -Port COM3 -Action Select -Channel 0
.\lib\host\audio_uart.ps1 -Port COM3 -Action Select -Channel 127
.\lib\host\audio_uart.ps1 -Port COM3 -Action Off
.\lib\host\audio_uart.ps1 -Port COM3 -Action Gain -EvenGain 200000 -OddGain 300000
.\lib\host\audio_uart.ps1 -Port COM3 -Action Gain -EvenGain 400000 -OddGain 400000
.\lib\host\audio_uart.ps1 -Port COM3 -Action Select -Channel 127 -LogPath log/i2s_parity/select127_uart_run01.log
```

`-LogPath` 可选，保存全部收发文本，路径必须未被使用。超时或状态不符时，错误包含最近收发记录及日志路径。关闭其他占用 COM3 的程序；不要同时运行配置工具、采集脚本或串口助手。曾有一次旧工具调用退出失败且未保存原始串口记录，原因未证实；该次随后捕获不能作为增益已应用的证据。

直接使用串口助手时，输入 `@I2S=0`（通道值可替换为 0～127）、`@I2S=OFF`、`@I2S?`、`@GAIN=EEEEEE,OOOOOO` 或 `@GAIN?`，每条以 CR/LF 结束。增益为非负 Q2.22，范围 `000000`～`7FFFFF`；`400000`=1、`200000`=0.5、`300000`=0.75。组增益对全部 64 个偶数通道或全部 64 个奇数通道生效；其后原逐通道校准继续工作。采用较大增益时仍可能饱和，不能靠组补偿修复已削波数据。

独立回应为 `I2S1` / `GAIN1`，每行 **14 个 8 位大写十六进制字**，单空格分隔、CRLF 结束；长度为 132 / 133 字节。SYS3 仍为原 34 字、312 字节，与两种音频帧按整行仲裁。完整字表见[UART 协议](system_uart_debug.md#独立音频命令)：

| 字索引 | 字段 |
|---|---|
| 0、1 | 音频回应序号；fresh/pending/reset/error/queue_overflow |
| 2、3 | 请求 / 实际 I2S 启用位与通道 |
| 4、5、6、7 | 请求 even/odd 增益；实际 even/odd 配置寄存器 |
| 8、9、10、11 | received_samples、output_frames、underruns、last_pcm |
| 12、13 | verified_frames、serial_errors |

flags bit0=fresh、bit1=pending、bit2=音频复位已释放；bit8..15 为错误码（0 成功、1 语法、2 越界），bit16..31 为队列溢出计数。一次发一条并等待回应，避免填满 8 深度队列。停止音频时钟时返回 fresh=0、pending=1，解析器把实际字段置为空；复位释放位不单独证明时钟正在运行。

请求配置保存在 27 MHz 监督域，系统/音频复位后自动重放；重新下载 FPGA 位流会恢复默认。实际快照通过跨时钟握手取得，配置 ACK 只表示已接收，pending 还比较实际 I2S 与实际增益，不能把“已收到命令”当作“已生效”。

## 数字实板自测与 DAC 验收

全通道测试使用单一COM3会话，逐一核对请求/保存/实际值与计数进展。实际FIR8结果见[本版报告](reports/i2s_fir8_auto_20261011.md)；旧B的[137案例](../log/i2s_parity/fir_fixed_result_hw_20261009/A/cases.json)和[原始UART](../log/i2s_parity/fir_fixed_result_hw_20261009/A/raw.log)只作历史示例。复测时关闭其他占用COM3的程序，使用新输出目录：

```powershell
.\lib\host\selftest_audio_board.ps1 -Port COM3 -OutputDirectory log/i2s_parity/board_audio_run01
.\lib\host\selftest_audio_board.ps1 -Port COM3 -AllChannels -OutputDirectory log/i2s_parity/board_audio_all_channels_run01
```

两行是不同范围的测试，选择一个未使用的目录运行。默认检查 0/1/127，`-AllChannels` 逐一检查 0～127；修正版上板验收应执行全通道版本。随后均检查 OFF、恢复、unity→even 0.5/odd 0.75→unity、非法帧不触发旧命令，以及 `r` 复位后通道 17/非默认增益自动重放。每个通道/工作状态至少两次查询，检查请求与实际状态匹配、fresh、pending、错误/溢出和输出/验证帧递增；启用时 PCM 接收数递增，OFF 时 LastPcm=0。最后恢复原请求通道/使能并将组增益设为 unity。`r` 会清除内部自测模式，后续网络 BIST 按 UART 指南重新启动。

输出 `raw.log`、`audio_records.json`、`system_records.json`、`cases.json`、`summary.json`。`SerialErrors=0`、`VerifiedFrames` 增加证明 FPGA 数字串行监测通过；它不能证明排线接到正确的 DAC 引脚、DAC 解除静音、模拟输出正常或 64 对麦克风幅值一致。

模拟验收需另存测量记录：在 PCM5102 端确认四个时钟/数据脚及供电，再用已知音源检查 OUTL/OUTR 的频率、幅度、削波和静音。所选通道在两声道输出相同数据，模拟左右输出也应对应；实际结论以测量为准。

## 64 对麦克风补偿校准

旧B退出BIST后的[F真实采样](../log/i2s_parity/fir_fixed_result_unity_20261009/analysis.json)为143,907帧/47,969包连续；其ch2/3全部−8,388,608、ACRMS0、rail100%，全帧饱和。前一seed3[144,156帧采样](../log/i2s_parity/dc_roundsat_seed3_unity_20261009/analysis.json)再次观察到同一DATA1/J26/AC22故障。当前FIR8自己的[F真实采样](../log/i2s_parity/fir8_auto_unity_spool_20261011/analysis.json)为143,589帧/47,863包连续；仅ch2/3有rail，且仍全部−8,388,608。正常通道均值变小不是AC配平或DAC模拟证据。[本次UDP暂存/离线解析用法](reports/i2s_fir8_auto_20261011.md#本次工程采集方式)保留原lib工具和验收阈值。

更早143,310帧/47,770包的[基线诊断](../log/i2s_parity/baseline_diagnosis.json)已标为INVALID_FOR_CALIBRATION。DATA1仍需检查接线、供电、LR选择及PDM波形；较小增益不能恢复丢失的音频，组零通过也不说明硬件故障已修复。

0.5/0.75只用于验证功能，**不是测得的声学校准系数**；验收完成或中断后都须核对unity恢复。组增益可用于共同的R/L差异，个体差异仍需逐通道校准，声学通过须覆盖全部64对。

1. 修复异常、确认真实模式 `SelftestMode=false`。把奇偶组增益设为 unity，核对逐通道 ROM 的增益均为 1、后级偏置为 0；记录 ROM、位流 SHA-256 和新鲜 GAIN1/SYS3 状态。新版本复位后保持安静稳定，等待 50 ms 预热、96 帧滤波稳定及4096帧直流估计审核，确认 `DcEstimationFinished=true`、`DcAnyChannelRejected=false`，且没有饱和/处理/丢帧标志。估计冻结后再开启标定声源，不为两份录音分别重置直流；记录中途复位或重训时重新采集。
2. 保持相同接线、供电、增益和声学几何，分别采集**已知等幅声场**与**安静背景**两份数据。等幅假设必须对每个 DATA 对成立；任意环境录音不能证明灵敏度比例。例中所有前缀须未被使用：

   ```powershell
   python lib/host/receive_pcm.py --bind 192.168.10.1 --seconds 5 --output log/i2s_parity/tone_before
   python lib/host/receive_pcm.py --bind 192.168.10.1 --seconds 5 --output log/i2s_parity/quiet_before
   python lib/host/calibrate_parity.py --tone log/i2s_parity/tone_before --silence log/i2s_parity/quiet_before --known-common-field --output log/i2s_parity/parity_proposal.json
   ```

3. 工具按通道去 DC、扣除背景噪声功率，再从 64 对 RMS 比例的对数中位数估计共同 R/L 比例，只衰减较强的一组。默认要求 64 对合格、每份至少 1,024 个干净稳定帧、SNR≥20 dB、激励 RMS≥−80 dBFS，预测每对残差≤0.5 dB。帧标志、满量程、源/epoch/帧号中断、元数据错位、低 SNR 或激励不足均不能用于正常校准；发生间断后重新跳过 96 帧。任一通道在捕获中触及满量程，其配对被排除，默认 64 对验收因此拒绝。
4. `PASS` 仅为候选系数；`NEEDS_PER_CHANNEL_CALIBRATION` 表示共同组增益仍无法使每对达到阈值，退出码为 2。输出 JSON 不会配置硬件或修改 ROM。不要降低 `--minimum-pairs` 来宣称全部麦克风已通过，也不要删除饱和标志以规避拒绝。
5. 把 JSON 的 `even_gain_q22` / `odd_gain_q22` 转成六位十六进制，通过 `@GAIN` 应用，并用 GAIN1 查询 fresh=1、pending=0、actual 匹配。保存应用命令和真实反馈。
6. 用新的等幅声场/安静捕获独立复测全部 64 对，记录每对 `20·log10(Aodd/Aeven)`、SNR、饱和率和帧完整性；其中 `A=sqrt(max(Var_tone−Var_quiet,0))`。全部配对符合阈值后才能报告 R/L 幅值一致。当前工具生成的是配置前候选，不自动签核配置后结果；已补偿数据不符合它的“unity 增益”声明，不应再次以该声明冒充独立验收。

## 当前验证证据

| 验证 | 结果与范围 |
|---|---|
| [FIR8完整功能回归](../log/i2s_parity/full_regression_fir8_auto_20261011.json) | 18/18 PASS，104项受测输入、22份向量，含8-lane两级FIR；seed3有独立历史回归，不混用 |
| [当前发布检查器测试](../log/i2s_parity/timingfix_fir_ram_strict_rows_checker_tests.log) | 214 项 PASS；检查器测试通过不等于本候选物理发布通过 |
| [FIR8严格发布](../fpga/build/MEMS_Array_i2s_fir8_auto_20261011/release.json) / [JTAG](../log/i2s_parity/jtag_fir8_auto_20261011/download.json) | 唯一1轮64819/64819路由成功，Slow setup/hold +0.016/+0.058ns、Fast +0.387/+0.020ns；16:19:06 SRAM下载PASS，未写Flash |
| [FIR8本次联合验收](../log/i2s_parity/fir8_auto_hardware_acceptance_20261011.json) / [F真实采样](../log/i2s_parity/fir8_auto_unity_spool_20261011/analysis.json) | PASS_WITH_KNOWN_ISSUES；A–E数字通过，C+D 504,694,272样本0错0缺包、D128路I2S内容通过，F143,589帧连续；DATA1/物理项目未验收 |
| [FIR8实板retry1](../log/i2s_parity/fir8_auto_hw_retry1_20261011/acceptance.json) / [retry2](../log/i2s_parity/fir8_auto_hw_retry2_20261011/acceptance.json) / [sync轮](../log/i2s_parity/fir8_auto_hw_sync_20261011/C/pcm_verified.json) | 原retry1/retry2 FAIL保留；sync修正UART启动后仍缺36,380包，整体FAIL；局部通过不代替完整验收 |
| [seed3历史物理发布](../fpga/build/MEMS_Array_i2s_parity_dc_roundsat_seed3_20261009/release.json) / [JTAG下载](../log/i2s_parity/jtag_dc_roundsat_seed3_20261009/download.json) | 首轮布线2小时23分2秒；严格快/慢角PASS，Slow全域最小setup +0.140ns、audio122 +0.190ns，最小hold Slow/Fast +0.057/+0.020ns；14:55:41 SRAM下载PASS，ID0x00603899、状态0x081ffca0 |
| [seed3历史：A：全部监听通道](../log/i2s_parity/dc_roundsat_seed3_hw_20261009/A/summary.json) | 137案例PASS，128/128路实际选通；请求/保存/实际值一致、fresh、无pending与串行错误；OFF、增益、非法命令、复位重放和恢复通过 |
| [seed3历史：B：真实组零增益](../log/i2s_parity/gain_zero_dc_roundsat_seed3_hw_20261009.json) | 偶数组48,012、奇数组144,087个稳定帧；各零组64路每个样本严格为零，另一组存在非零数据，unity已恢复；子结果PASS_WITH_KNOWN_ISSUES，保留未归零组ch3/ch2满量程 |
| [seed3历史：C：PHY/MDIO→ARP→UDP BIST](../log/i2s_parity/dc_roundsat_seed3_hw_20261009/C/pcm_verified.json) | 578,691帧、74,072,448个样本匹配独立oracle；错帧、错误标志、连续性及主机采集错误均为零 |
| [seed3历史：D：I2S内容与BIST旁路](../log/i2s_parity/dc_roundsat_seed3_hw_20261009/D/uart/summary.json) / [并行UDP](../log/i2s_parity/dc_roundsat_seed3_hw_20261009/D/pcm_verified.json) | 128路各至少4次快照、至少2个不同值，匹配各通道16值oracle；非unity配置下BIST内容仍为unity。UDP比较430,055,424个样本PASS；计数不是绝对PCM帧号 |
| [seed3历史：E：退出与恢复](../log/i2s_parity/dc_roundsat_seed3_hw_20261009/E/summary.json) | real、unity、I2S0/启用恢复；两次fresh GAIN查询通过，DC启用/审核结束/有拒绝均true，27条DC就绪SYS3；stickyCLIP如实保留 |
| [seed3历史：F：恢复后真实采样](../log/i2s_parity/dc_roundsat_seed3_unity_20261009/analysis.json) | PASS_WITH_KNOWN_ISSUES；144,156帧、48,052包连续；DATA1/ch2、3全部−8388608，ACRMS0、rail100%，全帧stickyCLIP；电压、DAC、声学未验收 |
| [seed3历史：独立DC实板验收](../log/i2s_parity/dc_roundsat_seed3_hardware_acceptance_20261011.json) / [外层原始文件绑定](../log/i2s_parity/dc_roundsat_seed3_hw_20261009_outer_invocation/result.json) | PASS_WITH_KNOWN_ISSUES；新位流/下载/38项生产与104项回归身份匹配，绑定真实命令/时间/退出码和E原始SYS3，不使用旧映像结果或mtime代替通过 |
| [I2S 独立验证](../log/i2s/result.json) | 128 通道选择、位序/帧边界/零填充/串行监测 PASS |
| [旧 B 奇偶补偿正式报告](reports/i2s_parity_fir_fixed_result_20261009.md) / [旧 B 原始回归归档](../log/i2s_parity/fir_fixed_result_before_dc_regression_20261009.zip) | 归档内 `log/parity/simulation.log` 保留旧 B 的 20,614 项检查 PASS，覆盖通道参数 1～128、分组边界、舍入饱和、帧边界更新、复位及 BIST 旁路；默认 128 通道为 131 拍。此行只证明旧 B 奇偶补偿，不包含新增 DC，不引用已更新的当前 `log/parity/result.json` |
| [seed3历史RAM回归](../log/i2s_parity/full_regression_dc_roundsat_20261009.json) / [FIR8六配置定向](../log/i2s_parity/fir8_directed_ram_20261011.json) | 基线四配置5,597,580项；FIR8六配置11,435,616项及18层回归通过，两级1090/2114拍；新版严格发布/JTAG及本次数字验收已通过；原捕获失败、DATA1和物理项目保留 |
| [音频 UART RTL 验证](../log/audio_uart/result.json) | 278,636 检查，291 行 SYS3 / 290 行音频帧；全部数字通道、128/999 拒绝、停钟、背压、短复位重放 PASS |
| [厂商 UART 技术网表](../log/vendor_uart/result.json) | 128 通道、55,197 检查、143 行回应 PASS；七位通道寄存器保留。验证到 dev_map，不含布线或 SDF |
| [板级音频集成](../log/board_audio/result.json) | 实际前处理到 I2S、真实模式无网运行、非默认增益、网络 BIST unity 旁路 PASS |
| [主机工具离线检查](../log/full_regression/host.log) | 11 个单会话 mock 正/负例 PASS；请求值或实际值不符、队列溢出、FPGA 拒绝及超时均不能误报成功，未打开真实串口 |
| [首版通道配置实测](../log/i2s_parity/board_audio_new_20261009/summary.json) | FAIL；选择 1/127 恒为 0。原始失败记录及首版位流保留 |
| [首版网络 BIST 实测](../log/i2s_parity/bist_first_verified_20261009.json) | PASS；187,984 包、563,952 帧、72,185,856 个样本逐位比较，无错帧、错误标志、连续性错误或主机丢包 |
| 首版真实模式组零增益 | [even=0 / odd=1](../log/i2s_parity/gain_zero_even_first_confirmed_20261009.gain_zero_even.json)：144,195 个稳定帧；[even=1 / odd=0](../log/i2s_parity/gain_zero_odd_first_confirmed_20261009.gain_zero_odd.json)：143,277 个稳定帧。各零增益组 64 路全部样本严格为零，另一组存在非零数据；`gain_zero_functional_pass=true`，状态为 `PASS_WITH_KNOWN_ISSUES` |
| [uartfix 历史候选](../fpga/build/MEMS_Array_i2s_parity_uartfix_20261009/manifest.json) | [17/17 功能回归 PASS](../log/i2s_parity/full_regression_uartfix_20261009.json)，物理时序 FAIL；发布门禁拒绝，无位流、未下载 |
| [timingfix 历史候选](../fpga/build/MEMS_Array_i2s_parity_timingfix_20261009/manifest.json) | 18/18 功能回归 PASS，旧 APM 宏编号约束导致布局 FAIL；无位流、未下载 |
| [timingfix2 历史候选](../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/manifest.json) | 176 个位置约束被原生工具接受；首次布线未完成时[主动取消](../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/cancellation.json)，最终时序未知，无位流、未下载 |
| [timingfix3 历史候选](reports/i2s_parity_timingfix3_20261009.md) | 18/18 功能回归、技术网表及 176 项宏位置审计 PASS；首次布线未完成时主动取消，最终时序未知，无位流、未下载 |
| [timingfix4历史候选](../fpga/build/MEMS_Array_i2s_parity_timingfix4_20261009/manifest.json) | 18/18功能PASS，完整构建FAIL、无发布位流；不替代旧B或当前seed3已完成的实板记录 |
| DAC 模拟与声学配对 | 待实测；DATA1/通道 2、3 故障未修复，不能据现有基线生成有效校准 |

首版组零跳过96帧并保留未归零组ch3/ch2的rail故障，见[恢复反馈](../log/i2s_parity/gain_restore_unity_first_20261009.json)。各版B使用独立前缀验证乘法，F另记录恢复后的真实unity采样；数字归零不是声学校准，首版局部通过也不抵消其选通失败。

独立重跑入口为 `sim/audio/run_i2s.py`、`sim/run_parity.py`、`sim/fir/run_ram_pipeline.py`、`sim/audio/run_audio_uart.py`、`sim/audio/run_vendor_uart.py`、`sim/audio/run_board_audio.py`；完整入口为 `sim/verify_all.py`。操作脚本的 `-Offline` 仅检查解析和语法，不打开串口，也不产生实板通过结论。
