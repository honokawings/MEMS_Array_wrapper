# 完整 UART 系统实板下载与网络测试

> 历史记录：2026-09-19 `MEMS_Array_uart_chain8` 修正前实板测试。正文中的“当前/本次/下一步”指当时状态。当前推荐位流与未完成实板项目见[最新发布报告](clk8_18v_update.md)，版本关系见[版本历史](version_history.md)。

2026-09-19 12:09–12:32，PG2L200H、COM3、ASIX 千兆网卡直连测试。**JTAG 下载成功，PHY/MDIO、ARP、UDP 实收通过；整体自测未通过，发现 FPGA 在启动/模式切换时等待 ARP 导致采样队列溢出。**

## 位流与下载

- 文件：`fpga/build/MEMS_Array_uart_chain8/generate_bitstream/mems_array_pg2l200h.sbit`
- SHA-256：`f8c38ae04039572f3efec5a593cc4b1089eed69c4975dbfb0e9c2e7a991a03d7`
- USB Cable II，JTAG 器件 ID `0x00603899`，识别为 PG2L200H。
- 使用 PDS `cdt_cfg_shell.exe` 连接本机已有 JtagServer，执行 CRAM 配置，没有写 Flash 或 eFuse。
- 两次配置均报告 DONE=1，状态寄存器 `0x081ffca0`，CRC、ID、认证和配置超时错误位均为 0。
- 当前硬件 RTL、约束和构建脚本的哈希仍与正式 manifest 完全一致，没有修改或重新构建位流。

首次配置后观察到异常的 UART 计数、历史 PHY 重试和非预期自测模式；首条 `r` 未确认，随后 `s`、`r` 均能正常应答。第二次配置捕获到从 250 ms 开始的干净 SYS3 启动，串口错误/未知命令、时钟故障和 PHY 重试均为 0。首次异常的根因尚未确定，不能据第二次成功宣称启动可靠性已充分验证。

本次 `-program 3` 两次用时 376.7 / 390.6 秒。第二次工具接受 `10MHz` 参数，但实际下载未加速，慢速根因未确定。目录中的 `download_sram_standard.tcl` 仅为准备的对照方案，**没有执行**，不能当成已验证的下载配方。

## 实测结果

| 检查 | 结果与证据 |
|---|---|
| UART / 时钟 | 第二次启动及后续命令正常；最终接收错误=0、未知命令=0，三个 PLL 锁定、四路频率合格、时钟故障=0 |
| PHY / MDIO | ID=`001CC916`，地址=1，配置步骤=27；PHYSR=`382E`，千兆全双工；重试=0，故障=0 |
| PC 网卡 | 指定网卡 `以太网 2`，MAC=`6C1FF71F1FBC`，IP=`192.168.10.1/24`，实测 Up、1 Gbit/s |
| ARP | PCAP 捕获 FPGA 请求和 PC 应答；FPGA 接受并解析出上述 PC MAC，接受计数=4 |
| UDP | PC 实际接收 `192.168.10.2:5000 → 192.168.10.1:5000`，约 16,000 包/秒；128 路、48 kHz、24 bit |
| 发送端 BIST | PASS，TX/分帧/RX_ER 错误均为 0 |
| 最终 5 秒样本 | 80,064 包，240,192 帧，30,744,576 个通道样本逐位匹配；捕获区间内无包/帧缺口、乱序、重复或主机队列丢弃 |
| 音频 BIST / 整体验收 | **FAIL**；最后一个会话启动时丢失 24 帧，Overflow 和自测失败标志锁存，最终采集的所有包仍携带历史错误标志 |

最终 10 秒 UART 观察中，UDP 完成计数增加 156,000（相邻首尾快照跨度 9.75 秒），丢帧计数始终为 24，没有继续增长。板上最终保留**内部 PDM 自测模式**；真实麦克风通道、输入电气连接和声学性能不在本次通过范围内。

## 丢帧定位

连续捕获模式切换前后 12 秒，收到 190,389 个 UDP 包。各 epoch 内 UDP 序号完全连续，主机队列丢弃和非法负载均为 0，但存在以下 PCM 帧缺口：

- epoch 3（真实输入模式）：包序号 6 的首帧为 135，前一帧为 113，缺 21 帧。
- epoch 4（内部自测）：包序号 6 的首帧为 138，前一帧为 113，缺 24 帧；与 UART `DroppedFrames=24` 完全一致。
- 两个自测区段共比较 55,212,672 个通道样本，数值不匹配为 0；严格核验仍因缺帧和错误标志返回 FAIL。

这把问题定位到 **FPGA 采样队列在 UDP 打包前发生溢出**。PCAP 中主机看到的 ARP 请求至应答间隔仅 31 / 24 µs，该间隔不包含 USB 网卡收发与 FPGA 实际接收的全部延迟，不能据此推断线上的完整往返时间。

源码对应关系：`mems_ethernet_core.sv` 用 `run && link_up` 同时启动采集和 MAC 会话；模式切换重载校准时 `run` 拉低，MAC 在 `!link_up` 分支清除 `peer_valid`。恢复后前端已产生 PCM，而 `ethernet_udp_engine.sv` 要等首包缓冲满才发 ARP。有限的帧 FIFO/跨时钟 FIFO 无法覆盖实际等待时延。

上位机脚本现已等 PHY 和 ARP 就绪后才发 `t`，将冷启动时的 48,026 帧丢弃降低至一次测试的 27 帧，但模式切换重新清空 ARP 后仍有溢出。因此**此脚本修改只是减少启动等待，未修复 RTL 问题**。

下一步 RTL 修正应将 PHY/MAC 的链路寿命与采集会话分离：物理链路建立后主动解析 ARP，得到对端后才释放采集；模式切换保留仍有效的对端信息，物理断链才清除。必须同时调整“首包满才请求 ARP”的条件，避免先等待对端、又等待 PCM 首包的死锁。回归需加入约 0.5–2 ms 的应答延迟、较长的主机地址探测等待、模式切换和断链重连，再重新生成并验收位流。

## 原始证据

全部位于 [board_test_20260919_1209](../../log/system_uart/board_test_20260919_1209/)：

- [综合结果 JSON](../../log/system_uart/board_test_20260919_1209/board_result.json)
- [最终下载日志](../../log/system_uart/board_test_20260919_1209/download_sram_10mhz.log)
- [干净启动串口](../../log/system_uart/board_test_20260919_1209/reconfiguration_startup_uart/summary.json)
- [修正主机等待后的 UART 自测](../../log/system_uart/board_test_20260919_1209/selftest_clean_uart/summary.json)
- [模式切换 ARP PCAP](../../log/system_uart/board_test_20260919_1209/arp_mode_transition.pcap)
- [模式切换 PCM 严格核验](../../log/system_uart/board_test_20260919_1209/pcm_mode_transition_check.json)
- [最终 5 秒 PCM 严格核验](../../log/system_uart/board_test_20260919_1209/pcm_final_check.json)
- [最终 UART 状态](../../log/system_uart/board_test_20260919_1209/final_uart/summary.json)

`analyze_evidence.py` 可从保留的原始文件重建综合结果。发布检查 PASS 是构建和物理实现验收，不能覆盖本次实板发现的启动丢帧问题。
