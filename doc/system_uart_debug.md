# 完整系统 UART 联调

> 当前下载版本为八路同源时钟、1.8 V 接口的 `MEMS_Array_uart_clk8_18v_spread3_long`：[位流](../fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/generate_bitstream/mems_array_pg2l200h.sbit)、[发布记录](../fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/release.json)均已完成，最终 PASS。下载前须实测 L6/L7 VCCIO=1.8 V。新版本尚未上板；下文2026-09-19 14:13版本及实测属于旧四路、3.3 V 方案。UART命令和网络参数保持一致，见[当前发布报告](reports/clk8_18v_update.md)。

本版将已在独立诊断中通过实板测试的以太网 PLL 修正合入完整采集系统：`I=4,M=16,F=2,O=4,OPTIMIZED`，PFD=31.25 MHz，输出仍为 250 MHz，经专用二分频生成 125 MHz。音频、PDM、PCM 和 UDP 数据格式不变。 当前修正版同时在 ARP 就绪后释放采集，模式切换保留 MAC 地址缓存；ARP 接收与重试独立于采集会话。

旧版正式构建为 `fpga/build/MEMS_Array_uart_arp_ready_routed/`，下载文件为其中 `generate_bitstream/mems_array_pg2l200h.sbit`。2026-09-19 14:13 生成，最终 `release.json` 为 **PASS**，`release_authorized=true`。位流 9,188,552 字节，SHA-256：`a5e591810e2e9855a1fb9ce4d14495da2d8babeb791bad667de825e0bf71fce3`。已 JTAG 下载并完成启动/模式切换数字链路验证；旧 `chain8` 位流和失败证据保留。详情见 [修正与实测报告](reports/arp_ready_fix.md)。

## 连接与串口控制

- COM3，115200 8N1，无流控。板载 CP210x 接 FPGA RX=B24、TX=C24，3.3 V。
- 上位机网卡保持 `192.168.10.1/24`；FPGA 为 `192.168.10.2`，UDP 目的端口 5000。
- UART 和观察器使用独立的 27 MHz 时钟，启动时将 PLL 复位保持约 20 ms。系统故障、软件复位及 PHY RXC 停振均不会阻塞串口。
- 每 250 ms 输出一行 `SYS3`。识别版本后才能发送本版命令；此前 `CLK2` 属于独立时钟诊断，不能当作完整系统状态。
- 不需要按键或 LED 组合。原物理 KEY0/KEY1 的复位/模式功能兼容保留。

| 单字符命令 | 行为 |
|---|---|
| `s` / `h` | 请求状态快照 |
| `r` | PLL/完整系统复位约 20 ms；回到真实麦克风模式；串口时基及命令计数不清零 |
| `t` | 向原自检控制器产生一次 100 ms 按键脉冲；消抖后切换内部 PDM 自测，两次命令间隔至少 0.2 秒 |
| `c` | 仅清除时钟历史故障；PHY/MAC 计数与其他错误需 `r` 重置 |

命令无需换行，CR/LF 被忽略。回执表示命令被识别，动作完成以随后新鲜状态为准。自测覆盖内部 PDM 源、128 路滤波/校准、打包和发送；上位机还需独立核对收到的样本。模式切换中止旧采集会话，重载 128 路校准并启动新 epoch；旧会话 TX 错误在新会话开始时清除，当前会话错误仍锁存。

## 实板逐级验收

2026-09-19 修正版已完成实板 PHY/MDIO → ARP → UDP 验证：FPGA 两级 BIST PASS，157,314,048 个通道样本逐位一致，启动与模式切换缺帧/溢出均为 0。模式切换期间 ARP 缓存保持有效，没有重新发起 ARP。恢复真实输入后，128 路全部为正满量程，阵列接入/供电与 DATA/CLK 状态仍待核对，不能将数字自检通过等同于声学验收。详见 [本轮报告](reports/arp_ready_fix.md)；[旧版失败记录](reports/uart_board_test_20260919.md) 保留作对比。

下载新位流后可先运行只读采集：

```powershell
.\lib\host\capture_system_uart.ps1 -Port COM3 -Seconds 15
```

自动复位并进入内部 PDM 自测：

```powershell
.\lib\host\capture_system_uart.ps1 -Port COM3 -Seconds 30 -SelfTest
```

自动脚本只在收到有效 `SYS3` 后发送命令：约 1 秒时 `r`；至少 4 秒，且时钟恢复、快照新鲜、校准完成、PHY 链路建立及 ARP 对端有效后才发送 `t`。脚本的等待条件保留；修正版 RTL 自身也等待 ARP，并在等待期间暂停采集，不依赖主机及时应答来避免启动溢出。结束后保持自测模式，便于继续捕获网络数据。日志目录默认 `log/system_uart/capture_时间/`，包含原始字符、解析记录和诊断摘要；退出会关闭 COM3。使用时关闭其他串口助手。

| 阶段 | 通过依据 | 未通过时重点查看 |
|---|---|---|
| 时钟/复位 | `ClocksHealthy=true`，稳态时钟历史无新异常 | lock/reset/frequency 掩码；采样域是否新鲜 |
| PHY/MDIO | `PhyId=001CC916`，`PhyReady=true`，`LinkUp=true`；PHYSR 低位满足 `(value & 003C)==002C` | MDIO 最近事务、ACK、扫描地址、失败 state/step/reg/data、重试计数及 PHY 复位 |
| ARP | `ArpRequestsSent` 增加；有效 ARP 到达后 `ArpAccepted` 增加、`PeerValid=true`，MAC 对应电脑网卡 | UART RX 原始帧计数与电脑二层抓包；区分无发送、无接收与解析拒绝 |
| UDP | FPGA `UdpSent` 持续增加，电脑 UDP 5000 实际收到包 | FPGA 计数只表示完成 GMII 发送；电脑无包时继续检查 RGMII/PHY/主机接收 |
| 自测数据 | FPGA 两个 BIST PASS；电脑收到连续、无错误标志且逐位匹配的 128 路样本 | 队列丢包、epoch/帧号缺口、滤波/校准和包内标志 |

PHY 扫描不存在的地址会产生正常的读无 ACK，不能仅凭 `MdioReadNoAcks>0` 判失败。结合 `PhyReady`、配置步骤、失败快照及重试次数判断。写事务没有 Clause22 ACK，`MdioAck` 仅在 `MdioRead=true` 时有效。PHY 历史 `fault` 在自动重试后仍保留，软件复位才清除。

在另一终端接收 5 秒 PCM（建议先等 UART 自测通过）：

```powershell
python lib/host/receive_pcm.py --bind 192.168.10.1 --seconds 5 --output log/system_uart/board_capture/pcm
python lib/host/verify_selftest.py --capture log/system_uart/board_capture/pcm --min-frames 48000 --output log/system_uart/board_capture/pcm_check.json
```

输出前缀必须未被使用。捕获脚本保存 PCM、逐帧元数据及缺帧/队列统计；5 秒数据约 92 MB。电脑端逐位比较通过后，才可称内部 PDM 到上位机的链路通过。本版不包含上位机 SRP-PHAT 算法，数字自测也不证明真实麦克风的声学性能。

如需二层证据，可复用 `log/hardware_debug/capture_npcap.py`，指定当前 FPGA 网卡的 Npcap 设备名，限定捕获 ARP 和 `192.168.10.2`。同时保存串口、PCAP 和 PCM 的时间与位流 SHA-256。无需修改防火墙来验证 PLL 或 MDIO。

如需验证启动或模式切换的首包连续性，必须先启动电脑接收器，再发送 `r`/`t`。单独捕获已经稳定运行的几秒数据无法排除先前发生的启动丢帧。真实输入 `Clipped=true` 或 UDP flags bit0=1 时，先检查输入和幅度；不要将这些包当作正常音频。

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
| 8 | bit0=started，1=acquiring，2=run，3=selftest_mode，4=overflow，5=processing_error，6=clipped，7=local pass，8=local fail，9=audio reset released，10=calibration_done，11=loaded_mode，19..23=原控制器状态 |
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

PHY 状态编号：0 复位、1 等待、2/3 读 ID1 请求/等待、4/5 读 ID2、6 下一个地址、7/8 配置请求/等待、9 轮询间隔、10/11 PHYSR 轮询、12 故障重试等待。配置步骤见 `rtl/net/rtl8211f_manager.sv`。

时钟故障掩码：bit0=公共/局部复位，bit1=96 MHz，bit2=音频，bit3=以太网。初始启动或主动复位期间当前故障非零是预期，历史故障在曾正常后才启用。

每条串口行在发送前冻结。audio、eth（包含 PHY 和 MAC）、rx 各自通过握手取得原时钟域内一致的快照，各域之间存在少量采样时差。新鲜位为 0 时相应字段仅为上次快照，不能当作当前状态。接收时钟停止不会无限等待；迟到的应答也不会被标成下一次请求的新鲜数据。

RX 帧计数只表示接收到 RX_DV，不保证一般帧的 FCS 正确；`ArpAccepted` 则经过原 ARP 解析器的格式、目标地址和 FCS 校验。相对频率计数无法测量绝对晶振误差、占空比或抖动。

## 构建与仿真

```powershell
python sim/verify_all.py
python -m unittest discover -s fpga/scripts/tests -v
python fpga/scripts/build.py --build-name MEMS_Array_uart_arp_ready_routed --stage gen_bit_stream
```

新增 UART 集成测试使用完整顶层、真实 PHY 管理器/MDIO 控制器、引脚级 PHY 模型、ARP 应答及 UDP 线上 FCS 检查；覆盖正常自测、发送中切换模式、RX 停钟、MDIO 无 ACK、自动恢复与软件复位。集成测试的 PLL/DDR 使用数字替身；实际厂商 PLL/DDR 原语由全量回归的独立项目验证。上位机脚本还直接解析 RTL 输出的串口字符，以验证协议字段一致。

发布检查要求 95 个实际引脚、全量回归、厂商 PLL 参数校验、双角时序、RGMII 实际物理偏差及 PDM 采样预算通过。新增 CDC 仍使用 7.5 ns 物理上界，27/122.88 MHz 超出 PDS 相位展开范围的提示单独审查，不放宽数据路径约束。
