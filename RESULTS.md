# 实验结果（2026-11-05）

环境：Python 3.12.3，Mooncake TE CUDA 13 wheel 0.3.14；源代码子模块固定 v0.3.14。未从源码编译。

所有实验使用 1 MiB CPU 内存模拟 KV，源端填充 0x5A。拉取方注册本地 buffer 后执行 transfer_sync_read，再逐字节校验全部 payload。

| 实验 | 源 → 拉取方 | Transport | 首次 READ 耗时 | 结果 | 日志 |
|---|---|---|---|---|---|
| 同机 TCP | .114 → .114（loopback） | MC_FORCE_TCP=1 | 2224.292 ms | PASS | tcp-target.log / tcp-pull.log |
| 同机 RDMA | .114 → .114 | mlx5_bond_0 | 27.869 ms | PASS | rdma-target.log / rdma-pull.log |
| 跨机 RDMA | 11.163.39.110 → 11.163.39.114 | mlx5_bond_0，两端 GID index 3 | 43.381 ms | PASS | cross-rdma-target.log / cross-rdma-pull.log |

## 解读与限制

- 耗时来自单次首次调用，包含握手和连接建立；没有热身和重复采样，不能据此比较 TCP/RDMA 性能或推导稳态带宽。
- 跨机数据路径：源 CPU DRAM → 源 RNIC → 网络 → 目标 RNIC → 目标 CPU DRAM。
- 使用 P2PHANDSHAKE，不需要 etcd 或 Mooncake Store。JSON 经 scp 交换服务地址、源地址及长度，不承载 KV payload。
- 没有运行模型、vLLM 或真实 KV block 调度；没有验证 GPU 显存直传。
- RDMA 日志存在 NUMA 查询权限及注销内存后的 fork 状态恢复警告；此次传输和数据校验成功，警告未解决。
- 日志保留原始时间戳、机器 IP、进程地址和诊断输出；地址不能用于重放，复现必须重新启动源端并刷新 JSON。
