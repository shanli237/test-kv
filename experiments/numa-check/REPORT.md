# 容器重新配置后的 NUMA 验证

2026-11-05，两端 Seccomp=0，Seccomp_filters=0。
本机和远端通过 numa_move_pages 查询自身已触页内存，均返回 rc=0、errno=0。

跨机验证：11.163.39.114 从 11.163.39.110 拉取 256 MiB CPU buffer。
固定两端 mlx5_bond_0，执行一次 READ，全部字节校验通过，调用耗时 38.098 ms（含首次连接和详细日志）。
分片日志为 source_location=cpu:1、target_location=cpu:1，不再是 *；未出现 Failed to get NUMA node。
证明 NUMA 查询权限及 TE 内存位置识别恢复。本实验固定网卡，不用于验证自动近端选择或多卡性能。

原始证据：local-query.json、remote-query.json、target.log、pull.log、result.json。
此次临时源进程已停止，target.json 中地址已失效。
