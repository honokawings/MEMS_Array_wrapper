# M128 上位机接口开发参考

接口文档版本：1.1（2026-09-17，自测标志扩展）；行为核对：2026-10-09，适用八路 CLK、1.8 V MEMS 和独立 I2S 音频的 UART 完整系统。UDP 头内的线协议版本仍为 **1**，长度和 PCM 布局不变；新增 flags.bit4/bit5。只接受旧版 0x0F 标志掩码的软件需要更新，不能把自测数据送入声源定位。

本文面向接收、存储、可视化及声源定位软件开发人员，可独立用于实现解码器。规范实现是 [pcm_protocol.py](../lib/host/pcm_protocol.py)，实际 RTL 发出的示例文件在 [protocol_examples](protocol_examples/)。FPGA 侧内部设计见 [传输规格](transport_spec.md)；操作步骤见 [自测指南](selftest.md)。

当前验证状态（2026-10-09）：**`MEMS_Array_i2s_parity_fir_fixed_result_20261009` 已发布并于 14:40:49 完成 JTAG 下载**，其[18/18 项功能回归](../log/i2s_parity/full_regression_fir_fixed_result_20261009.json)、128 路 UART 配置、奇偶独立零增益及实板网络/I2S 数字自测通过。UDP 线协议仍为 v1，SYS3 和独立 I2S1/GAIN1 字段保持不变；FIR 实现调整未改变数据值、frame_id 或 48 kHz 抽取间隔。结果与位流绑定见[本版本交付报告](reports/i2s_parity_fir_fixed_result_20261009.md)。DATA1/ch2、3 仍固定负满量程，电压、DAC 模拟输出与声学配平尚未验收。

[第一版](reports/i2s_parity_20261009.md)的网络通过与 UART 通道号恒为 0、[UART 修复候选的时序失败](reports/i2s_parity_uartfix_timing_20261009.md)，以及[timingfix4 参数对照](reports/i2s_parity_timingfix4_20261009.md)的超时/取消均保留为历史。未完成布线的时序仍为未知，旧通过结果不计入本版本验收。

## 1. 网络连接与业务边界

| 项目 | 默认值 |
|---|---|
| 物理链路 | RTL8211F-CG，1000BASE-T，全双工；10/100M 不发送 PCM 数据 |
| FPGA MAC | `02:00:00:00:01:28` |
| FPGA IPv4 | `192.168.10.2` |
| 电脑 IPv4 | `192.168.10.1`，建议网卡配置 `/24` |
| UDP 源端口 / 目的端口 | `5000 / 5000` |
| 拓扑 | 同一二层网段，直连或千兆交换机；无网关路由 |
| ARP | FPGA 主动解析电脑 MAC，也响应目标为本机的 ARP 请求 |
| 启动 | 校准完成后正常板级真实音频自动运行；UDP 等待千兆全双工与 ARP，不需要上位机启动命令 |
| 未实现 | DHCP、ICMP/ping、TCP、VLAN、远程配置命令、重传、应用层 ACK |

常规 UDP socket 的一次 `recvfrom` 返回一整个 **1208 字节 UDP 负载**，不包含 Ethernet/IP/UDP 头。应保留数据报边界并检查长度；不能把 UDP 当作无边界字节流。建议接收缓冲区至少 2048 字节，避免截断。

IPv4 使用 20 字节头，UDP 长度为 1216，IP 总长度为 1236，小于 1500 MTU，不产生 IP 分片。FPGA 生成 IPv4/UDP 校验和与 Ethernet FCS；普通 socket 的链路校验由网卡及操作系统负责，应用仍须验证 M128 长度、字段和序号。

网络参数为构建时配置；多板并用时须使用不同 MAC/IP，并按源 IP、源端口区分流。本协议不提供运行时改地址命令。

## 2. 数据量与容量规划

128 通道，每通道 48,000 样本/秒，有符号 24 位。一个“采样帧”指同一帧号下全部 128 通道的样本，不是一个 Ethernet 帧。

| 数量 | 值 |
|---|---:|
| 单采样帧 PCM | 128 × 3 = 384 字节 |
| 单采样记录 | 8 字节 frame_id + 384 字节 PCM = 392 字节 |
| 单 UDP 负载 | 32 + 3 × 392 = 1208 字节 |
| 包率 / 稳定阶段包间隔 | 16,000 包/秒 / 平均 62.5 μs |
| 原始 PCM | 18,432,000 字节/秒，18.432 MB/s |
| UDP 负载 | 19,328,000 字节/秒，154.624 Mbit/s |
| 线路预算 | 163.072 Mbit/s，含 Ethernet 头、FCS、前导码和 IFG |
| 30 秒原始 PCM | 552,960,000 字节；元数据须另留空间 |

PC 接收会受网卡合包、线程调度和缓冲影响，单次到达间隔不保证 62.5 μs。吞吐应在稳定区间统计；不要用收到一包的时刻作为该包内全部样本的采样时刻。建议接收和写盘分线程，队列有界并显式计数丢弃；参考工具使用 8192 包队列、申请 8 MiB socket 缓冲。

## 3. 公共头：偏移 0～31

**头内所有多字节整数为无符号大端；PCM 样本为有符号 24 位小端。** 禁止把收到的缓冲区强制转换为本机结构体后直接读取。

| 偏移 | 长度 | 字段 | 类型 / 必须检查的值 |
|---:|---:|---|---|
| 0 | 4 | magic | ASCII `M128`，十六进制 `4D 31 32 38` |
| 4 | 1 | version | u8，1 |
| 5 | 1 | header_bytes | u8，32 |
| 6 | 1 | encoding | u8，1 = s24le |
| 7 | 1 | channels | u8，128；不是有符号 int8 |
| 8 | 4 | sample_rate_hz | u32be，48000 |
| 12 | 2 | frame_count | u16be，3 |
| 14 | 2 | record_bytes | u16be，392 |
| 16 | 8 | packet_sequence | u64be，当前 epoch 内从 0 递增，模 2⁶⁴ |
| 24 | 4 | epoch | u32be，会话号，模 2³² |
| 28 | 4 | flags | u32be，定义见下表 |

### 状态位

| 位 / 掩码 | 名称 | 语义及上位机处理 |
|---|---|---|
| bit0 / 0x01 | saturation | 本轮前处理运行曾饱和；普通网络重连不清除，按应用质量规则处理 |
| bit1 / 0x02 | preprocessor_queue_overflow | 本轮前处理队列曾整帧丢弃；普通网络重连不清除，用 frame_id 定位具体缺口 |
| bit2 / 0x04 | processing_schedule_error | CIC/FIR/奇偶补偿/校准调度异常；前端重启前保持，停用该运行的定位数据 |
| bit3 / 0x08 | packetizer_framing_error | 打包器检测到通道/帧结构异常；本会话内保持 |
| bit4 / 0x10 | selftest_data | 内部模拟 PDM 数据；这是模式标志，不是故障；不得送入声学定位 |
| bit5 / 0x20 | selftest_mismatch | 自测 PCM 数值、顺序、流水线或进度检查失败；本次自测流内保持；只在 bit4=1 时有效 |
| bit6～31 | reserved | 当前必须为 0；拒绝未知值，等待明确的新协议定义 |

健康实采包通常 `flags=0x00000000`；健康自测包为 `0x00000010`；自测校验失败可能为 `0x00000030`，也可能同时带其他错误位。建议 `is_selftest = (flags & 0x10) != 0`，`has_error = (flags & 0x2F) != 0`。`0x20` 单独置位属于无效报文。

bit0～2 聚合三帧收集时观察到的状态；bit3～5 在本包提交发送前取值。因此标志不能精确定位某个样本，故障检出前已经提交的包也可能还没有错误位。保持型标志不表示每个后续包都新发生一次故障。bit0～2 在前端停用或复位时清除；正常板级仅网络 epoch 改变不清除它们，不能把重连当作调度错误已经恢复的依据。bit3 随网络打包器复位清除，bit5 随 BIST 会话重启清除。

## 4. 三条采样记录与样本解码

第 r 条记录起始位置 `p = 32 + r × 392`，r=0、1、2，对应偏移 **32、424、816**。记录头 `p..p+7` 是 u64be `frame_id`；第 c 通道的三个 PCM 字节位于 `p+8+3c`，c=0..127。

样本为 24 位小端二补码，范围 −8,388,608～8,388,607。把它转成浮点满幅比例时使用 `value / 8388608.0`，不要除以 8388607。该比例不是 Pa 或 dBSPL；绝对声压还需要实测灵敏度和声学校准。

| 字节（低字节在前） | 数值 |
|---|---:|
| `00 00 00` | 0 |
| `01 00 00` | 1 |
| `FF FF FF` | −1 |
| `00 00 80` | −8,388,608 |
| `FF FF 7F` | 8,388,607 |

C/C++ 可使用以下无对齐要求的转换；`p` 应指向已经完成长度检查的三个字节：

```cpp
#include <stdint.h>
static int32_t read_s24le(const uint8_t *p) {
    uint32_t u = (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16);
    return (u & 0x800000u) ? (int32_t)u - 0x1000000 : (int32_t)u;
}
static uint64_t read_u64be(const uint8_t *p) {
    uint64_t u = 0;
    for (unsigned i = 0; i < 8; ++i) u = (u << 8) | p[i];
    return u;
}
```

Python 推荐直接使用已验证的解码器：

```python
from lib.host.pcm_protocol import decode_payload

packet = decode_payload(udp_payload)  # 不传 Ethernet/IP/UDP 头
if packet.flags & 0x10:
    pass  # 路由到自测显示/校验，不能进入声源定位
else:
    for frame in packet.frames:
        samples = frame.samples()   # 128 个 Python 有符号整数
        # 按 source + epoch + frame_id 管理时间窗
```

64 位 packet_sequence/frame_id 超过 2⁵³ 后不能用 JavaScript Number 精确表示；应使用 BigInt 或在 JSON 中编码为十进制字符串。

## 5. 通道与采样时间

DATAk 对应两个通道：`2k` 为 LR=GND，`2k+1` 为 LR=VDD。当前板级输出八路同源 3.072 MHz CLK；实际负载分组由阵列接线决定，不改变通道编号。报文中始终按通道 0～127 排列。物理阵元三维坐标须由阵列机械/布线表提供，不能根据螺旋阵列或连接器顺序猜测。

正常时间轴上，相邻 frame_id 相差 1 表示相隔 1/48000 秒。`frame_id=m` 对应前处理输入的第 `64m+63` 个 PDM 周期，滤波公共群延迟为 2285.5 个 PDM 周期，即 743.977865 μs。以本轮启动等待结束后的第一个有效 PDM 周期为 t=0，可写成：

`t_effective(m) = (64m + 63 − 2285.5) / 3,072,000 秒`

该相对时间定义以 flags.bit2=0 为前提。它不提供 UTC/PTP/GPS 绝对时间，也不能用于自动同步不同 FPGA。单板通道共享帧号和相同滤波延迟；串行读取或网络发送顺序不会引入阵元间的采样时间差。新启动直流补偿增加共同等待时间，不改变 frame_id、抽取间隔、滤波群延迟或上述采样时刻定义，接收器无需因此改变解码或时间换算。有效定位通带为 20 Hz～16 kHz；新板级真实模式移除估计后冻结的稳定直流。

每次前端重新启动，先等待 153600 个 PDM 周期（50 ms），再丢弃前 96 个 PCM 帧。新板级真实模式随后估计 4096 帧直流，首个可输出帧为 **4192**；BIST 和默认禁用估计的便携内核仍为 **96**，无拥塞且接收器已开启时 BIST 首包通常包含 **96、97、98**。这些启动帧不补零、不伪造 frame_id。正常板级真实前端可早于网络就绪运行，UDP 只从网络释放后的完整帧开始发送，因此即使 packet_sequence=0，首个 frame_id 也可能大于 4192；普通网络重连不会将前端 frame_id 重置，也不会重训直流。接收器中途启动时，首次看到的编号还可能更大，不应据此报告开始接收之前的丢失。

## 6. 会话、停止、丢包与乱序

源 IP、源端口和 epoch 构成运行期间的网络会话键。epoch 标识网络流重新释放，packet_sequence 在新 epoch 内从 0 开始；它不保证前端同时重新启动。两种编号须分别解释：

| 事件 | 正常板级真实音频（INDEPENDENT_AUDIO=1） | 网络与上位机处理 |
|---|---|---|
| 断链、ARP 失效后恢复 | 保留校准及冻结直流，前端及 I2S 继续，frame_id 不重新计数 | 清空网络队列和未完成包；ARP 有效后以完整帧开始，新 epoch、包号从 0 开始 |
| 模式切换或停用 run 后重启 | 停止前端并重新等待稳态；模式切换时重载校准。新板级真实模式重训直流后首帧 4192，BIST 首帧 96 | 旧网络流清空；条件满足后建立新 epoch，首个网络帧取决于释放时刻 |
| 全局复位、重新下载或 PLL 失锁 | 前端重新启动并等待稳态 | epoch 计数器也复位；另建运行标识与采集文件 |

可移植网络内核默认 `INDEPENDENT_AUDIO=0`，内部 PDM BIST 也保持网络门控：这两种模式的断链重连同时重启前端时间轴，再等待 50 ms 并丢弃 96 帧。退出自测重新载入正常校准 ROM，恢复保留的奇偶增益；普通正常模式网络掉线不重载校准。

全局复位、掉电、重新下载或 PLL 失锁会把 epoch 计数器归零，首个流重新使用 1；仅凭报文无法唯一识别跨硬复位的会话。此时上位机应关闭旧采集文件并创建新的运行标识。不能把相同 epoch 跨重启合并成连续数据。

正常板级 ARP 未就绪时只暂停 UDP 分支，真实音频持续供 I2S 使用；这段 PCM 不进入网络队列、不在恢复后补发。可移植默认和 BIST 才暂停前端采集。模式切换保留 ARP 缓存，物理断链或全局复位清除缓存。已建立的网络流若发送端阻塞且有限缓冲耗尽，前处理按整帧丢弃并设置 bit1；网络反压也可能影响共享 PCM 监听。网络或 PC 接收拥塞会丢 UDP 包，FPGA 无法从 UDP 感知 PC 是否收到数据。

每条记录独立携带 frame_id，同一包内三帧也可能有间隙。新的网络 epoch 应切断原定位时间窗，即使前端 frame_id 在两个 epoch 间仍连续，也不能把未传送区间当成已完整收到。停止或切换时未完成的三帧尾部直接丢弃，不发送短尾包或结束标记。

建议按以下顺序处理每包：

1. 验证来源、1208 字节长度、固定头字段、标志掩码及三条记录边界。
2. 按会话跟踪包号和每条记录的帧号，明确记录缺口、重复和乱序。
3. 自测数据分流至测试工具；调度错误会话停止用于定位。其他故障按应用质量策略处理。
4. 为 SRP-PHAT 组窗时要求同源、同 epoch、帧号连续，并检查质量标志。缺帧时切断窗口或采用明确的上层算法处理；不能静默补零后宣称连续采样。

参考接收器保留到达顺序，不自动去重/重排/插值。`missing_observed_range` 只统计该会话首次观察到最高已观察序号之间仍缺失的数量，乱序补齐后会减少；`forward_gap_observations` 是累计跳号观察值，不等于最终丢包数。`continuous_with_previous` 仅表示相邻关系，不代表音频质量合格。

## 7. 无麦克风自测与验收

通过 UART 确认当前模式并发送 `t` 进入自测，bit4=1；完整步骤见[自测指南](selftest.md)。内部源使用固定 pattern_id=1：1024 个 PDM 周期重复，稳态 PCM 为 16 帧周期；128 通道具有不同特征，包含约 3 kHz 方波分量及四组相位。它模拟的是确定性数字激励，不能视为理想单频正弦，更不能证明声学 SNR。自测使用单位逐通道增益/零偏置，并将奇偶补偿按单位增益旁路而不覆盖已安装配置；仍经过实际 PDM 同步采集、CIC、两级 FIR、补偿、校准、FIFO、打包和 Ethernet MAC。BIST 参考中的首帧 96 不适用于推断正常板级重连时的首个网络帧。

预期 PCM 表是 [selftest_pcm.bin](../lib/host/selftest_pcm.bin)：16×128 个 s24le，按 `frame_id % 16` 再按通道索引；SHA-256 为 `fb653a4b25043495c2f54b36fbe9df7a9d9d6df06cbb95ce1d888bec444dc75e`。其生成结果经过独立 Python/C++ 定点模型交叉核对。今后改变激励或滤波系数时必须同步发布新参考；接收程序不能假设任意新版固件都采用这份旧表。

完整操作：

```powershell
python lib/host/receive_pcm.py --output captures/bist01 --seconds 10
python lib/host/verify_selftest.py --capture captures/bist01 --min-frames 48000 --output captures/bist01.check.json
```

先按自测指南进入模式后采集；验证切换首包时，接收器先启动，再通过 UART 切换模式。校验器跳过普通数据，至少验证 48,000 个自测帧，逐字节比较所有通道，同时检查错误标志、序号连续性和已知主机队列丢弃。`status=PASS` 表示本次收到的自测数据及观察范围内连续性满足要求。它输出 PC 到达时间估算的包率、PCM 帧率及 UDP 负载吞吐；此速率包含操作系统调度影响，不是时钟计量结果。校验失败返回非零退出码。

UART `SelftestTxPass` 仅说明 FPGA 已完整发出足量 UDP 包及 FCS，不能证明 PC 已接收；接收后逐样本校验才覆盖到上位机的链路。等待超时和故障处理见[自测操作指南](selftest.md)。

本版本两次实板 BIST 共比较 506,273,664 个样本，数值错误、错误标志、连续性错误和主机错误均为 0；进入 BIST 捕获的 25,900 个普通包已按模式跳过，持续 70 秒捕获没有普通包跳过。自测模式位 bit4 仍为 1，不能将“无错误标志”解释为整个 flags 字段为 0。恢复真实模式后另捕获 143,907 个连续帧，其中通道 2、3 每个样本都为负满量程；这种真实输入异常不能由协议正确或 BIST PASS 排除。见[验收与真实输入记录](reports/i2s_parity_fir_fixed_result_20261009.md)。

## 8. 可直接用于联调的真实报文

[二进制样例](protocol_examples/selftest_packet_v1.bin)、[十六进制样例](protocol_examples/selftest_packet_v1.hex) 与 [解码结果](protocol_examples/selftest_packet_v1.json) 来自真实板级 RTL 仿真的 GMII 输出，已剥离 Ethernet/IP/UDP 头。长度 1208 字节，SHA-256：`0ee3bf2bd10ae3fc20716fc977197b85b958497e5889b638ec4299566ab5fcdb`。

公共头的 32 字节为：

```text
4d 31 32 38 01 20 01 80 00 00 bb 80 00 03 01 88
00 00 00 00 00 00 00 00 00 00 00 01 00 00 00 10
```

应解码为 sequence=0、epoch=1、flags=0x10，frame_id 为 96、97、98；第一帧通道 0～3 为 −3248570、−5381647、−5010411、−2633031。样例可用于独立软件单元测试：

```powershell
python lib/host/receive_pcm.py --check doc/protocol_examples/selftest_packet_v1.bin
python -m unittest discover -s lib/host/tests -v
```

## 9. 参考接收器文件接口

`.pcm24le` 保存到达顺序下的 384 字节采样帧；`.frames.jsonl` 每帧一行，提供 byte_offset、frame_id、epoch、packet_sequence、flags、selftest、源地址、包内索引及连续性信息；`.summary.json` 提供保存数量、selftest_packets、flagged_packets、队列丢弃及会话统计。`flagged_packets` 只统计故障位，不把健康 bit4 自测模式当成故障。

`arrival_monotonic_ns` 是同一主机单调时钟的收包时间，同包三帧相同。它不能与其他 PC 的值直接比较。原始 PCM 必须和 JSONL 配套使用；异常退出后的尾部长度需重新核对。完整命令选项与性能边界见 [host_capture.md](host_capture.md)。
