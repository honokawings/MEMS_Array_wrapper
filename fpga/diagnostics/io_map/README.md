# 按键与LED映射诊断

> 历史专项诊断：五键五灯映射专项工具。当前八路 CLK / 1.8 V 完整系统使用 UART SYS3，入口见[联调指南](../../../doc/system_uart_debug.md)与[当前发布报告](../../../doc/reports/clk8_18v_update.md)。下文位流及操作仅适用于该专项工具。

器件：PG2L200H / FBB676 / -6。引脚来源：项目所附MINI硬件手册第13、34～35页，以及README中的麦克风时钟映射。两个工程独立于麦克风系统；源文件、约束和仿真集中在本目录，输出位于`fpga/build/IO_DIAG_DIRECT`和`fpga/build/IO_DIAG_WALK`。

**实板结果：通过。** 用户确认直接版与流水版的五键、五灯均按表对应：KEY0→LED0、KEY1→LED1、KEY2→LED2、KEY3→LED3、KEY4→LED4。基础IO映射与按键/LED功能已验证，无需修改这些引脚。流水版也确认D18参考时钟能驱动扫描逻辑；尚未测量其准确频率，不代表完整系统的PLL链或网络功能通过。原始观察记录见 [board_observation.json](../../../log/io_map_diag/board_observation.json)。

## 第一步：直接映射版

下载 [io_map_direct.sbit](../../build/IO_DIAG_DIRECT/generate_bitstream/io_map_direct.sbit)。以其 [release.json](../../build/IO_DIAG_DIRECT/release.json) 中的SHA-256核对文件。

下载完成后，**不按键时五个用户LED全灭是正常现象**。分别按住每个用户按键约1秒，预期仅对应的一个LED亮；松开即灭。也可以同时按两个键，对应两个LED应同时亮。

| 操作 | 输入管脚 | 预期亮灯 | 输出管脚 | 实际观察（待填） |
|---|---|---|---|---|
| KEY0按住 | C22 | LED0 | A20 | LED0，通过 |
| KEY1按住 | C23 | LED1 | C19 | LED1，通过 |
| KEY2按住 | B22 | LED2 | C18 | LED2，通过 |
| KEY3按住 | A22 | LED3 | E18 | LED3，通过 |
| KEY4按住 | B20 | LED4 | A17 | LED4，通过 |

此版本为`led = ~key_n`的组合通路，**没有时钟、PLL、消抖、状态机或按键复位**。KEY0在此处与其他四键地位相同。按键机械抖动不作隐藏，观察稳定按住后的结果即可。若没有响应，应检查按键是否为手册中的底板用户按键、实际电平及板卡硬件版本，不能归因于PLL未锁定。

只凭这一步可验证按键与灯之间的成对关系；若输入、输出同时发生编号置换，成对测试可能碰巧仍匹配。因此需要下一步独立验证LED编号。

## 第二步：流水识别版

下载 [io_map_walk.sbit](../../build/IO_DIAG_WALK/generate_bitstream/io_map_walk.sbit)，松开全部按键。该版直接使用D18的27 MHz时钟，**没有PLL，也不将任何按键用作复位**。以其 [release.json](../../build/IO_DIAG_WALK/release.json) 核对文件。

从配置启动开始，每个状态持续1秒，10秒一轮：

| 秒数（循环内） | 图案 |
|---|---|
| 0～1 | 五灯全亮 |
| 1～2 | 全灭 |
| 2～3 | 五灯全亮 |
| 3～4 | 全灭 |
| 4～5 | 仅LED0亮 |
| 5～6 | 仅LED1亮 |
| 6～7 | 仅LED2亮 |
| 7～8 | 仅LED3亮 |
| 8～9 | 仅LED4亮 |
| 9～10 | 全灭，然后重复 |

不要根据左右位置预先猜编号；记录实际亮起的丝印及顺序。该序列对应的物理输出顺序固定为A20→C19→C18→E18→A17。两次全亮/全灭是每轮的起始标记。

按住任意键时，按键组合直接覆盖灯图案，行为与直接版相同；松开后继续显示正在运行的图案，**不会从第0秒重启**。如果某个输入一直为低，图案会一直被按键显示覆盖，因此不流水时先检查是否有常亮灯、按键卡住或输入缺少上拉。

寄存器使用厂商`GTP_DFF`的`INIT=0`及配置全局复位；不依赖软件延迟或未知的外部按键复位。仿真使用实际Pango原语模型，并缩短每个状态的时钟周期数。

## 结果判断

| 实测结果 | 优先检查 |
|---|---|
| 两版的五键、五灯均按表对应 | 基础IO映射成立，返回系统调试，观察PLL锁定/复位及PHY状态 |
| 流水图案正确，某个按键没有反应 | 对应按键输入电平、连接和丝印；记录实际输入映射 |
| 图案存在但亮灯顺序与丝印不同 | 记录实际LED对应关系，结合实物原理图更新引脚映射 |
| 直接版正常、流水版静止且无按键覆盖 | 检查D18的27 MHz参考及其板间连接；直接版不受此时钟影响 |
| 直接版未按键却有灯常亮 | 对应输入可能低有效、卡住或接错；测量释放电平 |
| 两版均完全无响应 | 核对Program完成、实物板型/版本、用户LED位置及IO电源，再测按键电平 |

两版均将四个麦克风时钟输出拉低，并保持G25的PHY复位为低，**网口掉线是诊断版的预期行为**。其用途是基础IO验证，不发送音频或以太网数据。测试结束后，重新下载原 [完整自测位流](../../build/MEMS_Array_selftest/generate_bitstream/mems_array_pg2l200h.sbit) 恢复完整系统。

建议使用JTAG进行临时下载。不要在本次诊断中执行Flash擦除/写入。位流文件存在、仿真及构建通过均不能替代上表中的实际按键观察。

## 工程与复现

在项目根目录执行：

```powershell
python fpga/diagnostics/io_map/build.py
```

默认依次构建直接版、流水版；可用`--variant direct`或`--variant walk`单独构建。只运行仿真：

```powershell
python fpga/diagnostics/io_map/build.py --sim-only
```

ModelSim脚本位于`tb_script/`。仿真日志为 [simulation.log](../../../log/io_map_diag/simulation.log)，结果为 [result.json](../../../log/io_map_diag/result.json)。测试覆盖两轮图案、32种按键组合、停钟时按键响应、KEY0不复位计数及配置全局复位恢复。

脚本先检查实际映射出的15/16个端口和双角时序，再生成位流；每个工程的`release.json`记录源码、仿真和位流哈希。构建时的`board_mapping_confirmed=false`作为历史快照保留，之后取得的实板通过结果单独记录在`board_observation.json`，不改写已发布构建证据。
