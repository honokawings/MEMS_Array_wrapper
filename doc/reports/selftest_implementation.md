# 按键自测实现与验证记录

> 历史记录：2026-09-17 按键自测版，包含后来发现的 PLL 参数问题。正文中的“当前/本次/下一步”指当时状态。当前推荐位流与未完成实板项目见[最新发布报告](clk8_18v_update.md)，版本关系见[版本历史](version_history.md)。

日期：2026-09-17。新增 RTL、上位机参考包和 PG2L200H 位流已完成。11 项完整功能回归通过，本轮从编译到位流生成的完整构建及最终发布检查均为 PASS；发布范围为工程上板联调，尚未实板验证。

## 功能与要求对应

| 要求 | 实现 | 验证证据 |
|---|---|---|
| 按键启动自测 | KEY1 两级同步、20 ms 消抖、每次按下切换一次 | `tb_board_selftest` 短抖动与切换；`tb_selftest_faults` 长按单次触发 |
| LED 显示状态 | LED0 心跳、LED1 模式、LED2 数值通过、LED3 发送通过、LED4 锁存故障 | 真实板级 RTL 状态观察及故障/超时定向测试 |
| 无麦克风测试前处理 | 内部64线双相PDM经过实际同步器、CIC/FIR/校准，不旁路为预制PCM | 外部 DATA 悬空；128通道源bit与PCM预期值核对；破坏PDM后检出故障 |
| 测试通信数据与速率 | 实际UDP/IPv4/ARP/MAC，报文携带自测及故障标志 | 原始GMII CRC/校验和、序号、样本与稳定段包率检查 |
| 增加后完整仿真 | 正常模式回归加自测端到端及故障用例 | `log/full_regression.json`，11项PASS |
| 上位机开发参考 | 独立接口文档、真实报文、标准库解析器和自测验收工具 | `doc/host_protocol_reference.md`、`doc/protocol_examples/`、主机15项单元测试 |

## 本轮功能结果

- 全量模型和厂商原语参与，所有11项通过；详见 [完整系统报告](system_verification.md)。
- 自测Python/C++独立定点模型：32,768个PCM样本逐位一致，128通道特征互不相同，稳态16帧重复。
- 板级自测线上输出：两个正常自测会话共40包、120帧、15,360个PCM样本，与黄金值全部一致；无自测样本错误、错误标志、包号/帧号缺口。
- 稳定段21个包间隔合计1,312,496 ns，预期1,312,500 ns；偏差来自两个时钟域与仿真时间量化，对应约16,000包/秒。启动缓冲阶段独立记录，未把首包间隔当成稳态。
- 故意把内部PDM源拉低后，真实滤波输出改变，自测比较器失败、LED4锁存，线上报文出现bit5。该故障包单独检查，不混入健康数据验收文件。
- 掉线重连重新开始源相位、计数及epoch；退出自测恢复外部输入；复位清除模式和灯状态。
- 单独覆盖未连接网线时等待超时、PCM停止超时、PHY/TX故障、通道/帧号错误、按键长按及故障锁存恢复。
- 上位机15项测试通过，包含真实UDP回环、正负24位边界、保留位检查、自测误码/错通道/错相位/缺包/重复包、文件长度/元数据损坏拒绝及到达速率计算。

证据目录：[log/selftest](../../log/selftest/)、[全量回归记录](../../log/full_regression.json)、[发布检查自测](../../log/fpga_audit_unit_tests_selftest.log)。ModelSim的自测编译与最终仿真均为零错误、零警告。

上位机交付包：`M128_Host_Reference_v1.1.zip`（历史包当前工作区缺失；现行资料见[上位机接口参考](../host_protocol_reference.md)及其链接的源码/样例），包含独立文档、严格解码器、接收器、自测比较器、6144字节预期表和真实报文样例。解压到独立目录后验证15个主机测试：14项通过，1项依赖完整FPGA回归fixture而明确跳过；原工程中该项已通过。包SHA-256为 `54941a97f583ffd067a637326a8da99910f127a187dd157a81860df827902358`。文档中的C/C++及Python片段也已运行，见 `log/selftest/protocol_doc_checks.json`。

主机解析、连续性检查和缓冲写盘基准：16,000包、48,000帧用时0.398秒，约40,234包/秒；PCM为18,432,000字节、元数据为16,433,553字节。该结果不包含网卡接收或fsync持久化，证据为 `log/host_capture_benchmark_selftest.json`。

## 物理实现

实际综合层次统计为31,626 LUT、36,959 FF、130 APM、54.5 DRM36K等效、3 GPLL、93 IO。与旧版同口径综合相比增加588 LUT、440 FF、1.5 DRM36K等效。比较器本身为203 LUT、155 FF和1.5 DRM36K等效；其ROM成功推断为片上存储，未展开为大量组合逻辑。

本轮布局布线最终使用35,922个物理LUT（CLMA 26,302 + CLMS 9,620）、36,962个FF、130 APM、54.5 DRM36K等效、3 GPLL、93 IO。物理LUT口径包含映射与布线阶段的变化，不与综合层次LUT混用。见 [布局布线资源报告](../../fpga/build/MEMS_Array_selftest/place_route/mems_array_pg2l200h.prr)。

新构建使用独立目录 `fpga/build/MEMS_Array_selftest/`，包含KEY1及5个LED共93个顶层端口。原GUI工程与旧发布工程保留。本轮构建于02:00:20开始，02:28:11完成位流生成，02:28:34最终发布检查通过；源码、系数、约束、回归、双角网表/SDF及位流由SHA-256关联。发布检查工具的91项单元测试通过。

### 双角时序与接口预算

下表为本轮原始布线后报告的最差余量，单位ns；所有建立、保持、恢复、移除及最小脉宽摘要均无失败端点。

| 路径 | 慢角建立 | 慢角保持 | 快角建立 | 快角保持 |
|---|---:|---:|---:|---:|
| 122.88 MHz音频域 | 0.161 | 0.045 | 1.667 | 0.020 |
| 125 MHz发送域 | 0.996 | 0.099 | 3.769 | 0.020 |
| 125 MHz接收域 | 2.015 | 0.116 | 4.505 | 0.028 |
| RGMII接收输入 | 0.140 | 0.143 | 0.387 | 0.495 |

- 64根PDM输入与4个时钟输出的实际布线路径已核对。138.346354 ns采样窗口中，慢角预算余量8.200354 ns、快角10.479354 ns；包含麦克风100 ns数据延迟、外部往返20 ns、FPGA路径及不确定性。新增KEY1使异步输入摘要包含65个端点，检查器仍单独追踪全部64个PDM采样寄存器。
- RGMII发送端实际引脚相对偏差最大0.279 ns，小于0.300 ns预算，另有PCB相对偏差0.200 ns预算。
- TXC名义占空比慢角48.8500%、快角51.6125%。按未定义口径的180 ps解释为逐沿±180 ps时，保守敏感性分析仍为FAIL（44.35%～56.1125%）；本轮布线允许的相邻边沿抖动上界为0.271 ns。发布记录明确保留该结果，不能据名义时序PASS宣称实板占空比已合格。

原始模型为PDS的 **Pre-silicon**；最终 [发布记录](../../fpga/build/MEMS_Array_selftest/release.json) 为 `status=PASS`、`release_authorized=true`、`scope=engineering_board_bringup`、`unconditional_board_qualification=false`。须按 [上板指南](../board_bringup.md) 实测TXC占空比/抖动和真实负载下的麦克风时钟。

### 发布文件

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| [mems_array_pg2l200h.sbit](../../fpga/build/MEMS_Array_selftest/generate_bitstream/mems_array_pg2l200h.sbit) | 9,188,552字节 | `890f36447042e3bd278de8382c69a68c301aff41aadf33f2c2a8a6d34c1f9d62` |
| [mems_array_pg2l200h.bin](../../fpga/build/MEMS_Array_selftest/generate_bitstream/mems_array_pg2l200h.bin) | 9,186,916字节 | `42b1b59cdcad60a960db53f731b46af2415f7898e23a21430a4066965e72e45a` |

Pango工程入口为 [MEMS_Array.pds](../../fpga/build/MEMS_Array_selftest/MEMS_Array.pds)。本次完整回归记录SHA-256为 `7438b02833f3fe81733b622ac8c6d60e2c9dea47f24a523c756025eac502b682`。最终交付文件与文档链接一致性核对见 [selftest_delivery_verification.json](../../log/selftest_delivery_verification.json)。

## 适用范围

数字自测覆盖完整数据路径和发送端进展，上位机验收进一步覆盖接收文件。尚未实板下载或测量；外部麦克风接线、时钟扇出、TXC实际抖动/边沿、长期实板通信和声学性能不由内部模拟数据证明。
