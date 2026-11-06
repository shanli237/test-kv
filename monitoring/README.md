# Mooncake READ 时间序列监控

## 运行

两端已部署 TE 和免密 SSH 时，在仓库根目录执行：

```bash
uv pip install --python .venv/bin/python -r monitoring/requirements.lock
ssh 11.163.39.110 'mkdir -p /workspace/FuseLink/testvllm/monitoring'
scp nic_probe.py 11.163.39.110:/workspace/FuseLink/testvllm/
scp monitoring/telemetry.py monitoring/sample_nics.py 11.163.39.110:/workspace/FuseLink/testvllm/monitoring/
.venv/bin/python monitoring/run_capture.py --remote 11.163.39.110
```

不传 `--remote` 时进行本机双进程验证。每次创建独立 UTC 时间戳目录 `experiments/telemetry/<run-id>/`，不覆盖旧结果。两端路径目前固定为本仓库路径，IP 可通过 --local-host / --remote-host 修改。
runner 固定两端 bond_0 和 CPU NUMA 0，依次执行基线、single、batch、parallel 和恢复间隔。默认每阶段 2 轮热身 + 24 轮测量，每轮 256 MiB，结束后逐字节校验。源端、采样进程在退出时清理。

## 采集层级

- 快速计数：8 张 bond 的所有 RDMA 端口，100 ms 读取收发字节/包数。
- 慢速计数：其余 sysfs counters、hw_counters 每项约 1 秒读取一次，错开到不同采样轮，减少单轮读耗时。存在时包含 ECN/CNP、重试、丢弃等计数；不支持的计数不伪造为 0。
- 原始记录含读取起止单调时钟、墙钟、读取错误、设备/NUMA/netdev 映射。
- 单调时钟计算同端速率；port_rcv_data/port_xmit_data 按标准 4 字节单位换算。负增量标记为重置，不生成负速率；其他硬件计数保留原单位。
- Python TE 调用事件：process-local transfer ID、模式、迭代编号、字节数、API start/end、返回码、完整校验事件。先缓存在内存，退出时写 JSONL，降低磁盘干扰；进程被 SIGKILL 时事件可能丢失。
- single 一个 API 调用；batch 一个 API 调用包含多个请求；parallel 四个线程分别记录实际进入 API 的事件。

## 输出

- `timeline.png` / `timeline.pdf`：两端网卡速率、应用侧在途调用/字节、API 延迟。
- `local-nics.jsonl` / `remote-nics.jsonl`：原始 sysfs 时间序列及设备元数据。
- `*-events.jsonl`：应用层 TE 事件，包含热身。
- `*-result.json`：测量耗时、完整校验和前后计数。
- `rates.csv`：逐采样区间平均速率。
- `summary.json`：采样读耗时、实际间隔、采样超时、错误、重置、硬件计数增量和 API 统计。
- `manifest.json`：范围、参数、时钟探测边界、成功/失败及清理状态。
- `phases.json`：阶段时间标记。

重新渲染：`.venv/bin/python monitoring/render_capture.py experiments/telemetry/<run-id>`。

## 如何解读

1. NIC 曲线是宿主机全局流量，不是本进程独占流量。其他卡有流量不能直接归因于本实验。
2. 100 ms 平均值不能还原几毫秒的瞬时突发。每轮清零/校验带来空档，因此曲线不是持续压满网卡的带宽基准。
3. 在途量是 Python-to-TE API 层的未返回调用，包含软件处理；不是硬件 QP 队列占用或已投递 WR 数。完成时间是 API 返回，不能等同于 CQE 的精确时间。
4. 此阶段不修改 TE C++ 实现，没有内部 post/CQE/retry 结构化事件；固定 bond_0 消除了选择歧义。后续自动多卡实验仍需分片亲和性日志或 C++ 埋点关联。
5. 本地事件与采样使用同一主机单调时钟；跨机使用持久 SSH 通道探测墙钟差并给出误差边界，远端曲线仅近似对齐。它不是 NTP/PTP 已同步的证明，也不包含采样读取窗口内的逐计数器时间误差。
6. inventory 只记录 RDMA device、NUMA、netdev、可见的 bond slaves，不保证覆盖厂商硬件 bond 映射。尚未确认物理端口聚合与速率口径，因此不显示“利用率百分比”，不累计可能重叠的逻辑/物理设备。
7. 采样 read_ms 衡量读取窗口，不是 CPU 利用率，也没有独立证明监控对吞吐零影响。

本工具不修改驱动、网络、交换机或 NIC 配置。原始实验仍使用 CPU 模拟 KV；尚未接入 vLLM/GPU KV。
