# 单卡与多卡 READ 路径实验

日期：2026-11-05。源端 11.163.39.110，拉取端 11.163.39.114。
使用 TE CUDA13 0.3.14 wheel，CPU mmap buffer；没有使用 GPU。

## 方法

四组组合：单卡/多卡 × 单请求/批请求。每轮传输 256 MiB，每组执行三轮，共校验 3 GiB payload。
源端和接收端各注册一块连续 256 MiB buffer；batch 将同一 buffer 切成 64 个 4 MiB 请求，一次调用 batch_transfer_sync_read。
每轮先清零接收 buffer，传输后逐块检查全部字节为 0x5A；校验不计入传输耗时。
单卡两端指定 mlx5_bond_0；多卡两端不指定 device，MC_TE_FILTERS 限定 mlx5_bond_0 至 mlx5_bond_7。
未启用轮询、网卡配对亲和性或应用层并发，保持默认选择策略。
开启 MC_LOG_RDMA_SLICE_AFFINITY=1 和 GLOG_v=1；日志中的分片长度为 64 KiB。

计数器采集范围为两端所有可读的 /sys/class/infiniband/*/ports/1/counters。
本机计数窗口覆盖三轮传输和数据校验；远端窗口还包含拉取进程初始化及退出。
每种网卡策略启动前采集一次空载背景窗口，中间等待 2 秒；包含 SSH/采集开销，实际窗口略长。

## 结果

| 配置 | 第1轮 ms | 第2轮 ms | 第3轮 ms | 校验 |
|---|---:|---:|---:|---|
| 单卡，1 × 256 MiB | 49.479 | 7.573 | 7.337 | 全通过 |
| 单卡，64 × 4 MiB batch | 37.551 | 9.276 | 9.033 | 全通过 |
| 多卡，1 × 256 MiB | 3749.780 | 3890.356 | 3677.610 | 全通过 |
| 多卡，64 × 4 MiB batch | 3823.822 | 3874.530 | 3649.537 | 全通过 |

这些是开启逐分片日志的诊断耗时；第一轮包含连接建立，不能作为严谨带宽基准。

### 网卡选择

- 单卡两组全部使用本地 bond_0 → 远端 bond_0：每组 12288 条分片日志，共 768 MiB，无带 retry_cnt 的分片重选日志。
- 多卡单请求三轮分别使用本地 bond_2、bond_1、bond_4；每轮初始分片分布到远端八张 bond，每张 32 MiB。本地并未在单轮内聚合八张卡。
- 多卡 batch 三轮分别使用本地 bond_4、bond_3、bond_6。即使拆为 64 个请求，同一注册 buffer 的选择复用仍使该次 batch 使用一张本地卡。这不代表不同内存布局/并发下也一定如此。
- 多卡两组均出现发往远端 bond_7 的 transport retry counter exceeded；日志显示随后重选远端 bond_0。每组额外出现 1536 条重试分片记录（96 MiB），不能当作额外有效 payload。
- 两端 NUMA 查询报 Operation not permitted，位置日志为 `*`。此次没有验证正确 NUMA 亲和性，也没有证据表明选到了机内最近网卡。

### 端口计数与限制

port_xmit_data / port_rcv_data 原始计数保留在 JSON 中；标准 RDMA sysfs data counter 单位为 4 字节。
本地单卡 batch 的 bond_0 接收增量为 205228261 单位，约 782.88 MiB，与 768 MiB payload 及协议开销相符。
多卡单请求本地主要接收增量出现在 bond_2、bond_1、bond_4；batch 出现在 bond_4、bond_3、bond_6，与选择日志一致。
但空载背景窗口本地 bond_0/bond_1 已分别发送约 253.83/240.26 MiB，远端也有明显背景流量。
因此计数器仅用于交叉核对，不能把全部增长归因于实验，也不能用这些端口计数还原逐跳交换机路径。
远端 bond_7 超时的根因尚未确定，不能仅凭本次实验断言网卡损坏或拓扑不通。

## 文件和复现

- `*-target.log`：源端日志；`*-single.log` / `*-batch.log`：拉取端分片及校验日志。
- `*-single.json` / `*-batch.json`：耗时、校验结果、本机前后计数。
- `*-remote-counters.json`：远端前后计数。
- `*-background.json`：无实验传输时的背景计数。
- `summary.json` / `summary.txt`：按本地/远端网卡配对聚合的提交分片及计数增量，含重试而非纯有效字节。

在仓库根目录运行 `.venv/bin/python run_nic_probe.py`，再运行 `.venv/bin/python summarize_nic_probe.py`。
前者使用已配置 SSH 的 .110，要求远端同路径下已有 `.venv` 和 `nic_probe.py`；如修改脚本需先 scp 同步。
重跑会覆盖本目录同名结果，应先保存旧结果。测试启动的两组源进程已停止；此前 1 MiB 演示源进程不受影响。

下一步定位建议：单独验证到远端 bond_7 的各端点可达性，再决定候选集或配对规则；本次未做并发扩展、GPU实验或网络配置修改。
