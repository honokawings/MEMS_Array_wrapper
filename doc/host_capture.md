# 上位机 PCM 采集

工具为 `lib/host/receive_pcm.py`，使用 Python 3.10 或更高版本的标准库，不需要安装第三方依赖。上位机开发完整参考见 [host_protocol_reference.md](host_protocol_reference.md)，FPGA侧规格见 [transport_spec.md](transport_spec.md)。

## 连接与运行

1. 将上位机网卡 IPv4 设置为 `192.168.10.1/24`，连接 FPGA 的千兆以太网接口；允许本程序接收 UDP 5000 端口。
2. 在工程根目录运行：

```powershell
python lib/host/receive_pcm.py --check
python lib/host/receive_pcm.py --output captures/run01 --seconds 30
```

默认监听 `0.0.0.0:5000`，仅保存来源 `192.168.10.2:5000` 的报文。使用 `--source-ip`、`--source-port` 匹配修改后的 FPGA 配置；`--source-ip any --source-port 0` 放开源地址过滤。未指定 `--seconds` 时持续采集，按 Ctrl+C 停止并写入总结。`--packets N` 在收到 N 个 UDP 数据报后停止，该数量包含不符合源地址过滤或协议校验的数据报。

文件名前缀必须未使用；工具拒绝覆盖已有采集。接收线程与写盘线程之间有 8192 包的有界队列。默认请求 8 MiB socket 缓冲区，实际获准大小记入总结文件；可通过 `--queue-packets` 与 `--receive-buffer` 调整。队列满时整包丢弃并增加明确计数，不插入虚构采样。

## 输出文件

| 文件 | 内容 |
|---|---|
| `run01.pcm24le` | 按接收顺序存放真实收到的采样帧；每帧 128 通道，每通道有符号 24 位小端，共 384 字节 |
| `run01.frames.jsonl` | 每个 PCM 帧一条 JSON，包含字节偏移、frame_id、epoch、packet_sequence、flags、包内位置、连续性与缺口 |
| `run01.summary.json` | 格式信息、保存数量、错误/丢弃计数、各源地址与 epoch 的序号统计 |

原始 PCM 文件本身没有时间标签，**用于定位时必须与 frames.jsonl 配套读取**。工具保留所有通过格式检查的数据，包括重复包和乱序包；这些情况会在元数据中标明。不会自动补零、插值、排序，也不会把掉线前后的采样拼成一个连续时间段。

例如前后两条记录的 `frame_id` 为 97 与 101 时，中间缺少 3 个采样时刻；后一条 `frame_gap_before=3` 且 `continuous_with_previous=false`。定位处理可以切断窗口，或根据帧号明确进行自己选择的缺失数据处理。不能仅凭文件偏移认为这两帧相隔一个采样周期。

每条记录的 `byte_offset` 指向 PCM 文件中该帧的 384 字节。`continuous_with_previous` 只有在源地址、epoch 相同，且与前一条实际写入记录的 frame_id 相差 1 时才为 true。会话切换的首帧始终为 false。`arrival_monotonic_ns` 是主机收到 UDP 包的时间，同包三帧共享该值；它不是麦克风采样时间。

epoch 仅用于两次全局复位之间区分链路会话；全局硬复位、掉电重启、重新烧录或 PLL 失锁恢复后可能重新使用先前的 epoch。上述情况后应停止接收器，并以新文件前缀重新启动采集。若继续写入旧文件，帧号回退处仍会被标记为不连续，原始记录仍保留，但同源地址、同 epoch 的累计统计会合并两次运行，不能按跨全局复位的单一会话解释；接收器不会凭报文内容猜测硬件重启或 PLL 失锁。

`flags` 的六个位与传输规格一致：bit0 饱和，bit1 前处理队列溢出，bit2 处理调度错误，bit3 帧结构错误，bit4 内部自测数据，bit5 自测校验失败。标志为包级状态；不能据此推断只有某一个通道或某一条记录发生异常。元数据的 `selftest` 等于 bit4；总结中的 `selftest_packets` 单独统计自测包，`flagged_packets` 只统计故障位（掩码0x2F）。自测包绝不能进入声学定位。

无麦克风联调时，按 KEY1 进入自测，正常接收后运行 `python lib/host/verify_selftest.py --capture captures/run01 --min-frames 48000`。它比较全部通道预期数据、检查连续性和故障，并输出观察到的接收速率。详见 [自测指南](selftest.md)。

`continuous_with_previous` 只描述源地址、epoch 和帧号的相邻关系，不代表样本质量或链路健康。特别是 bit2=1 表示前处理未按时完成，此后连续帧号也不能证明实际采样时间连续；该会话不得继续用于声源定位，应排除时钟/调度故障后重启采集。饱和样本和帧结构错误同样须由应用按质量规则排除；bit1 的具体丢帧位置则依据 frame_id 缺口判断。

`packet_status` 与 `frame_status` 的值包括 `start`、`contiguous`、`gap`、`out_of_order`、`duplicate`、`before_capture`。这里的 contiguous 相对该会话已见到的最高序号，逐条实际写入是否相邻应以 `continuous_with_previous` 判断。

## 丢失统计的边界

- `missing_observed_range` 表示同一源地址/epoch 从首次观察序号到最高已观察序号之间仍未收到的序号数；迟到报文填补缺口后会减少。开始采集前和结束采集后的数据不计为丢失。
- `forward_gap_observations` 累计首次向前跳号时观察到的缺口，之后迟到补齐不回减，所以它不能等同最终丢包数。
- `host_queue_dropped_packets` 是本进程因写盘队列满而明确丢弃的数据报数量。`invalid_payload_packets` 是长度/版本/字段不符合协议的数据报数量。
- 普通 Python UDP socket 无法跨平台获取网卡/操作系统的精确丢包数，`os_socket_drop_count` 保持 null；包序号缺口可能来自网络或主机接收损失。只有 frame_id 缺口而包号连续时，通常来自 FPGA 前处理丢帧。
- 意外终止或磁盘写入错误可能留下不完整文件。总结只保证正常关闭时的完整写入数量；恢复时用 JSONL 完整行与 PCM 文件长度核对，不能把未配对的尾部当作有效数据。

## 离线验证与调用

```powershell
python -m unittest discover -s lib/host/tests -v
python lib/host/receive_pcm.py --check path/to/rtl_payload.bin
python lib/host/receive_pcm.py --check path/to/rtl_payload.hex
python lib/host/receive_pcm.py --check log/net_core/payloads.hex --golden tb/vectors/expected_pcm.bin
```

`--check` 无文件参数时使用固定已知字节验证网络字节序、24 位符号扩展和帧号缺口。带文件参数时接受单包或多个连续 1208 字节 UDP payload；不包含 Ethernet/IP/UDP 头。`.hex`/`.mem`/`.txt` 支持空白分隔十六进制字节及 `//`、`#` 行尾注释。单独的格式检查不会替代数值比较；增加 `--golden` 后，将每条记录的 frame_id 作为黄金模型帧下标，逐通道对照小端 int32 黄金文件，报告比较样本数及源数据 SHA-256。

应用程序可导入 `lib.host.pcm_protocol.decode_payload`。返回包内三条记录，每条 `.pcm` 为原始 384 字节；需要数值时调用 `.samples()` 返回 128 个有符号整数。实时保存路径不执行逐通道数值展开，以减少接收开销。

本机解析与写盘性能可用 `python lib/host/tests/benchmark_capture.py --packets 16000` 测量。该测试包含字段校验、连续性统计、PCM/JSONL 缓冲写入与关闭文件；不包含真实网卡收包，也不代表断电持久化性能。整机是否无丢包仍应以上板持续采集后的序号统计为准。

2026-09-16 在当前工作站运行 16,000 包测试：48,000 帧全部保存，耗时 0.391 s，约 40,916 包/s，高于业务所需的 16,000 包/s。写入 PCM 18,432,000 字节、元数据 15,617,553 字节；原始结果见 `log/host_capture_benchmark.json`。这是该工作站缓冲写入路径的测量值，不是网卡持续接收或磁盘持久化带宽的保证。

2026-09-17 增加自测标记后重新运行同一16,000包基准：0.398秒，约40,234包/秒，48,000帧无缺口；结果见 `log/host_capture_benchmark_selftest.json`。该测量仍仅覆盖解析与缓冲写盘。
