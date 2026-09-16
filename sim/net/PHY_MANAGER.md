# RTL8211F-CG 启动与 MDIO 回归

从项目根目录运行 `python sim/net/run_phy.py`。独立库为 `sim/net/work_phy`，完整编译、仿真及源文件 SHA-256 记录在 `log/net_phy/`。不依赖网络或厂商 PHY 仿真库。

## 顶层集成

先编译 `rtl/net/mdio_clause22.sv`，再编译 `rtl/net/rtl8211f_manager.sv`。管理模块全部状态和输出状态标志在 `clk` 域，`rst_n` 为低有效复位。板级 MDIO 连接示例：

```verilog
assign eth_mdio = mdio_oe ? mdio_out : 1'bz;
// rtl8211f_manager.mdio_in <- eth_mdio
// rtl8211f_manager.phy_rst_n -> RTL8211F PHYRSTB
// rtl8211f_manager.mdc       -> RTL8211F MDC
```

板级需存在 MDIO 上拉。`mdio_oe=1` 表示 FPGA 驱动，封装为厂商 IO 三态原语时注意原语的使能极性。`ready && link_up` 为允许千兆发送的条件；`fault` 是历史故障粘滞指示，恢复链路后仍保留，直到外部复位，不宜把它作为永久禁止发送条件。状态跨时钟域时另行同步。

| 参数/输出 | 含义 |
|---|---|
| `CLK_HZ=125000000` | 真实管理时钟频率；用于所有时间计算 |
| `MDC_HZ=1000000` | 目标 MDC 频率；实际会向低速取整，并限制在 2.5 MHz 以下 |
| `RESET_CYCLES=CLK_HZ/50` | PHY 低有效硬复位至少 20 ms |
| `SETTLE_CYCLES=CLK_HZ/20` | 释放硬复位后等待至少 50 ms |
| `POLL_CYCLES=CLK_HZ/100` | 相邻链路查询之间等待 10 ms，再加本次 MDIO 读交易时间 |
| `RETRY_CYCLES=CLK_HZ` | 配置错误/MDIO 无应答后等待 1 s，重新硬复位、扫描和配置 |
| `phy_address[4:0]` | 配置成功后为发现的真实非零地址；扫描期间是当前候选 |
| `ready` | 初始化和配置回读全部成功；运行期 MDIO 无应答立即清零并重试 |
| `link_up` | PHYSR 实时链路有效、速度 1000 Mbps、全双工同时满足 |
| `fault` | 扫描无设备、配置回读失败或运行期 MDIO 无应答置位，仅外部复位清零 |

PHY 硬件电源、25 MHz 晶体以及 `clk` 必须在释放模块 `rst_n` 前稳定。仿真缩短复位/等待参数仅用于加速用例，生产工程保留合规默认值。

## 初始化与依据

本地依据为开发板资料 `4_IC_datasheet/Ethernet_PHY/C187932_以太网收发器_RTL8211F-CG_规格书_WJ14392.PDF`，文档标题 RTL8211F(I)-CG/RTL8211FD(I)-CG、Rev.1.4：

1. §7.17、手册第 30 页要求低电平硬复位至少 10 ms，释放后至少 50 ms 才访问寄存器。本实现使用 20 ms/50 ms。
2. §7.11、表 12/13 规定 Clause22 帧格式及读 `Z0`/写 `10` turnaround；表 59、手册第 57 页给出 PHY 输出数据延迟最大 300 ns。实现每笔交易完整发送 32 位前导码，在 MDC 上升沿后充分等待，再经两级输入同步采样。
3. 表 11 说明地址 0 默认是广播地址。本实现扫描 0 后继续寻找非零 ID 匹配；如果到 31 均无非零匹配、但 0 曾匹配，才回退到 0。首次非零匹配即停止，避免向其他器件写配置。表 24/25 给出 RTL8211F-CG ID `0x001cc916`，使用完整匹配，拒绝 RTL8211E 等不同型号。
4. RGMII TX/RX 内部延迟位由 [Linux 官方 Realtek 驱动](https://github.com/torvalds/linux/blob/master/drivers/net/phy/realtek/realtek_main.c) 的 `RTL8211F_RGMII_PAGE`、`RTL8211F_TX_DELAY`、`RTL8211F_RX_DELAY` 和 `rtl8211f_config_rgmii_delay()` 核对：页 `0xd08` 的寄存器 `0x11` bit 8、`0x15` bit 3。两位均置一，匹配 FPGA 引脚输出时钟和数据边沿对齐的 RGMII。公开 Rev.1.4 未列出这两个延迟位，代码只更改上述已确认的位并回读。
5. 表 26 的 ANAR 清除 10/100 广告、PAUSE、远端故障、额外 next page；表 31 的 GBCR 打开 1000 Mbps 全双工，关闭测试模式和手动 master/slave。保留该器件 GBCR bit 8 的原值，因为其手册定义为保留位。
6. 表 33/34/51 规定 Clause22 间接 MMD 访问以及 EEEAR。通过寄存器 `0x0d/0x0e` 访问 MMD 7、地址 `0x003c`，读改写清除 bit 2（1000Base-T EEE）和 bit 1（100Base-TX EEE），保留其余位并回读。随后才重启自协商，避免协商到 EEE/LPI 带来额外唤醒延迟；不直接修改需要软件复位的 PHYCR2。
7. 表 22 的 BMCR 打开并重启自协商，保持正常工作、非隔离、非回环，同时设置 1000 Mbps 全双工的强制模式字段。回读忽略自清零的 Restart_AN bit 9。
8. 表 39 的 PHYSR 位于页 `0xa43`、寄存器 `0x1a`：bit 2 为实时链路、bit 3 为双工、bits 5:4 为速度；只有 `(value & 0x003c)==0x002c` 才输出 `link_up=1`。使用实时寄存器避免 BMSR 锁存低需要连续读两次的问题。

配置字段采用读改写，保留无关/保留位；页选择及各个实际更改的字段均回读校验。管理器独占此 MDIO 接口，正常轮询时页面保持 `0xa43`；若系统将来增加第二个 MDIO 主机，需要另加仲裁和页面状态维护。

## 已覆盖的独立验证

自检只通过真实 MDC/MDIO 引脚解码交易，PHY 模型使用手册规定的 300 ns 最大输出延迟。覆盖非默认地址 5/7、地址 0 广播响应、另一个 RTL8211 型号干扰、32 地址全无应答、读 turnaround、写 turnaround、前导码、三态争用、MDC 周期、配置字段回读与保留位完整性。

链路用例覆盖 100/10 Mbps、千兆半双工拒绝、拔线及恢复、MDIO 消失后的 fail-closed 与完整硬复位恢复、历史故障保持和外部复位清零。EEE 用例验证正确 MMD 地址/访问模式、保留位不变、自协商重启前完成关闭，以及写入未生效时 fail-closed。额外实例用未覆盖的默认复位/等待参数验证实际 20 ms/50 ms 时间。

该回归是数字 RTL/协议验证；PCB 走线、真实 IO 电压及 RGMII 时序由板级约束和实板验证确认。
