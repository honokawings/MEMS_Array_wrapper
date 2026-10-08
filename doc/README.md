# 文档索引

核对日期：2026-09-20。当前推荐版本为 **`MEMS_Array_uart_clk8_18v_spread3_long`**：八路同源 CLK、1.8 V 麦克风接口、UART 完整系统。工程发布 PASS；本版尚未下载，实际 L6/L7 电压及实板功能待确认。

## 操作指南

建议阅读顺序：项目概览 → 上板指南 → UART 联调 → 内部自测 → 真实阵列采集。

| 文档 | 用途 |
|---|---|
| [项目 README](../README.md) | 当前状态、系统规格及唯一完整接线表 |
| [上板与采集](board_bringup.md) | 供电、接线、推荐位流、JTAG 下载及重建方法 |
| [UART 联调](system_uart_debug.md) | COM3 控制、SYS3 协议及 PHY/MDIO → ARP → UDP 验收 |
| [内部 PDM 自测](selftest.md) | 无麦克风条件下的 FPGA 自测与上位机逐样本校验 |
| [PCM 采集](host_capture.md) | 接收工具、文件格式、连续性与丢包统计 |

## 设计与接口规范

| 文档 | 适用范围 |
|---|---|
| [算法冻结规格 v1.0](algorithm_spec.md) | 系数、定点格式、抽取相位与时间轴 |
| [RTL 微架构](rtl_architecture.md) | 调度、存储、跨时钟域及诊断结构 |
| [集成与运行](integration.md) | 可移植前处理接口、依赖及校准 |
| [传输规格 v1.1](transport_spec.md) | FPGA 发送行为、数据包和会话定义 |
| [上位机接口参考](host_protocol_reference.md) | 解码、样例、质量标志与接收验收 |
| [PHY 管理器](../sim/net/PHY_MANAGER.md) | MDIO 初始化、状态机及专项验证 |

算法规格 v1.0、传输文档 v1.1 和 UART `SYS3` 是不同接口的版本标识。M128 UDP 头内的线协议版本仍为 **1**，本次文档整理未改变协议或数据格式。

## 当前验证证据

| 证据 | 已证明的范围 |
|---|---|
| [当前发布报告](reports/clk8_18v_update.md) | 推荐位流、SHA-256、引脚、电气配置、资源及双角时序 |
| [最终 release.json](../fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/release.json) | 本次构建的源文件、报告、回归及产物绑定；工程发布 PASS |
| [系统功能回归](reports/system_verification.md) | 自动生成，12/12 功能仿真与模型校验通过 |
| [前处理验证](reports/verification.md) | 自动生成，前处理模块及数值比较 |
| [性能仿真](reports/performance.md) | 自动生成，冻结系数与数值模型性能；不是声学实测 |
| [检查器测试日志](../log/system_uart/clk8_checker_tests.log) | 146/146 发布检查器测试通过 |
| [发布检查规则](../fpga/scripts/RELEASE_CHECK.md) · [RGMII 证据说明](../fpga/scripts/TX_SOURCE_CHECK.md) | 工程发布判据、物理时序与未确认的实板边界 |

发布范围为 `engineering_board_bringup`。数字功能、器件模型时序、真实板级电气和声学性能分开记录；前三份自动生成的功能/性能报告不应手工改写测试数据。

## 历史与资料

[版本历史](reports/version_history.md) 集中列出旧位流、旧实板结果和诊断报告。旧版 157,314,048 个样本通过属于四路 CLK 版本，不能作为当前八路/1.8 V 版本的实测验收。

厂商原件保持原名：

- [盘古 MINI 系列开发板硬件指导手册 V1.3](盘古MINI系列开发板硬件指导手册_V1.3.pdf)：板卡、Bank 供电与接线。
- [IM72D128V01 数据手册](IM72D128V01XTMA1.pdf)：麦克风参数与 PDM 电气时序。
- [原始前处理需求](history/original_requirements.md)：最初范围与实现步骤。

维护文档时，完整接线表以根目录 README 为入口，发布数值以对应构建的 `release.json` 为证据；操作文档引用这两处，避免复制旧版本状态。版本变化后同步检查上板、UART、自测及主机协议说明。

本次整理的[核查记录](../log/documentation_cleanup_20260920/audit.json)包含本地链接、表格结构、README 引脚解析和现有发布文件哈希检查。修改前文档保存在 `log/documentation_cleanup_20260920/originals/`；RTL、约束、位流及自动生成的测试报告保持原样。
