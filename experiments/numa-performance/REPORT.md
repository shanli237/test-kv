# NUMA 恢复后的单卡 / 多卡跨机 READ 对比

日期：2026-11-05；源 .110 → 拉取端 .114；TE CUDA13 wheel 0.3.14。

## 结论

Mooncake 确实可以使用多张网卡。CPU NUMA 0 内存优选本 NUMA 的 bond_0–3，而非必须只选唯一一张卡。开放八卡时，本次未使用跨 NUMA 的 bond_4–7。
但允许多卡与单次请求本地带宽聚合不同：诊断中的单请求、batch 每次各选一张本地卡；四路并发才观察到同一轮使用多张本地卡。

## 控制与方法

两端 Seccomp=0。进程线程限制到 NUMA 0 可用 CPU，在该节点首次写入 mmap buffer；未使用 mbind 强制内存策略。诊断日志全为 cpu:0 → cpu:0，NUMA 查询没有失败。
两端各注册一块 512 MiB CPU buffer，源填充 0x5A，每次拉取前清零目标，每次返回后完整分块校验；清零和校验不计入 transfer 计时。

- single：1 × 512 MiB READ。
- batch：128 × 4 MiB，一次 batch_transfer_sync_read，同一注册 buffer。
- parallel：线程池四路同时提交，每路读取互不重叠的 128 MiB；计时等待全部完成。
- 单卡：两端只允许 bond_0，显式 device=bond_0。
- 多卡：两端 MC_TE_FILTERS 允许 bond_0–7，不显式指定 device；使用默认随机/缓存策略，没有手工给线程分配网卡。

诊断运行每组一轮，开启逐分片日志；性能运行关闭逐分片日志，另起进程。
第一轮性能热身 2 次、测量 10 次；发现单请求/batch 的新端点建立尖峰后，独立复测热身 8 次、测量 20 次。
每轮都完整校验；所有组均通过。两次性能测试分别保存在本目录与 ../numa-performance-warm。

## 主要性能结果：热身 8 次，测量 20 次

GB/s 为十进制有效 payload 吞吐（536870912 / 中位耗时 / 1e9），非网卡线速。

| 负载 | 单卡中位 ms | 单卡 GB/s | 多卡中位 ms | 多卡 GB/s | 多卡/单卡 |
|---|---:|---:|---:|---:|---:|
| single | 11.509 | 46.65 | 9.526 | 56.36 | 1.21× |
| batch | 11.468 | 46.81 | 9.722 | 55.22 | 1.18× |
| parallel 4 | 11.432 | 46.96 | 5.254 | 102.18 | 2.18× |

多卡三组最大耗时分别为 9.857、10.446、5.507 ms；本轮未出现此前秒级超时或 NUMA 查询错误。
第一轮独立 parallel 运行：单卡 46.85 GB/s，多卡 185.73 GB/s，约 3.96×。第二轮未复现这一较高数值，不能承诺稳定四倍收益。
默认选择、连接缓存和线程调度可能影响并发分配；性能轮关闭逐分片日志，不能把其波动唯一归因于网卡碰撞，尚未做因果隔离。

## 实际网卡选择证据

详细日志运行（每组一轮 512 MiB）：

- 单卡三种负载全部本地 bond_0 → 远端 bond_0。
- 多卡 single：本地 bond_2，远端 bond_0–3 各 128 MiB。
- 多卡 batch：本地 bond_1，远端 bond_0–3 各 128 MiB。
- 多卡 parallel：本地 bond_2 与 bond_3 各 256 MiB，分别与远端四卡通信。即四个请求没有保证占四张不同本地卡。

注意诊断运行和性能运行是不同进程，选择结果不能直接等同。
性能复测 parallel 的本机端口计数：bond_0–3 各接收约 3.567 GiB，bond_4–7 无 data counter 增量；28 轮有效 payload 合计 14 GiB，其余为协议开销等。
单请求在多轮间也可轮换网卡，所以总计数上多张卡有流量，并不证明单次请求在本地同时聚合多卡。

CPU 拓扑源码将同 NUMA 的 HCA 全部列为 preferred_hca（topology.cpp discoverCpuTopology），GPU 的距离筛选策略不同。本结论适用于此次 CPU buffer，不等同于 GPU KV cache。

## 限制

背景计数、两端原始计数和日志全部保存，计数器为宿主机范围，非进程独占。
组间按顺序运行，未随机化测试顺序；仅两次独立运行。结果用于机制研究，不是性能保证。
网卡端点选择可观测；未监测逐跳交换机路径、PCIe/UPI 硬件流量。
此前 bond_7 超时没有在本次重现，因为 NUMA 0 优选路径未选到它；不代表 bond_7 问题已解决。

## 复现与文件

仓库根目录：

```bash
scp nic_probe.py 11.163.39.110:/workspace/FuseLink/testvllm/
.venv/bin/python run_numa_perf.py
.venv/bin/python run_numa_perf_warm.py
.venv/bin/python summarize_numa_perf.py
```

重跑会覆盖同名结果，先备份。固定实验 IP 和目录；两端需同版本环境。
原始性能 JSON 含每轮耗时和本机计数；*-remote-counters.json 为远端计数；*-background.json 为背景窗口。
summary.json 汇总两次结果及诊断分片配对字节数。local/remote-topology.txt 保存 GPU/NIC 拓扑。
临时源进程已停止，probe-*.json 元数据已失效且排除版本管理。
