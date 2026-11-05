# Mooncake TE 拉取实验

环境：`.venv`，Python 3.12，mooncake-transfer-engine-cuda13 0.3.14。
源码：`Mooncake/` 固定在 `v0.3.14`（运行的是发布 wheel，尚未从源码编译）。
依赖锁定：`requirements.lock`。

## 双进程 READ

在本目录运行。终端 A：

```bash
source .venv/bin/activate
python pull_demo.py target --protocol rdma --device mlx5_bond_0 --host 11.163.39.114 --info target-rdma.json
```

看到 READY 后，终端 B：

```bash
source .venv/bin/activate
python pull_demo.py pull --protocol rdma --device mlx5_bond_0 --host 11.163.39.114 --info target-rdma.json
```

源端保持运行，Ctrl+C 停止。每次重启源端，必须使用新生成的 JSON。
示例只注册 1 MiB CPU 内存并写入固定模式，模拟 KV payload；不是模型生成的 KV。
目标端调用 transfer_sync_read 后校验全部字节。
使用 P2PHANDSHAKE，无需 etcd 或 Mooncake Store。

TCP：两端都改用 `--protocol tcp`，去掉 `--device`，使用另一个 `--info` 文件。
脚本设置 MC_FORCE_TCP=1，防止自动发现 RDMA 后改变路径。

跨节点：两端 --host 分别使用各自可达 IP，源端 JSON 复制到目标节点；两端必须有相同环境、可达的握手端口及可用 RDMA 网络。已验证同机和跨节点 CPU 内存传输；尚未验证 GPU 显存直传。

## 已验证

- 强制 TCP：1 MiB READ，逐字节校验通过，日志 tcp-target.log / tcp-pull.log。

- RDMA / mlx5_bond_0：1 MiB READ，逐字节校验通过，日志 rdma-target.log / rdma-pull.log。
- 日志中的 NUMA 查询权限警告和 deregister 后 fork 状态恢复警告仍存在，未影响此次数据校验。
- 单次耗时包含首次连接，不作为带宽测量。

## 代码阅读入口

1. pull_demo.py：注册源/目标内存，发布源地址，发起 READ。
2. Mooncake/mooncake-integration/transfer_engine/transfer_engine_py.cpp：transferSyncRead → transferSync。
3. Mooncake/mooncake-transfer-engine/src/transfer_engine_impl.cpp：引擎与 transport 调度。
4. Mooncake/mooncake-transfer-engine/src/transport/rdma_transport/：RDMA 请求、队列及完成检测。

安装复现：

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.lock
```

## 跨机器 RDMA（已验证）

2026-11-05：源端 11.163.39.110 → 拉取端 11.163.39.114。
两端 TE 0.3.14，mlx5_bond_0，GID index 3；1 MiB CPU buffer READ 全字节校验通过。
首次 READ 43.381 ms，包含连接建立，不代表稳态性能。
日志：cross-rdma-target.log、cross-rdma-pull.log。

本次实验结束时源进程保留运行（当时 PID 10021，1 MiB buffer）。仅在源进程仍存活且本机已取得最新 JSON 时，才能重跑：

```bash
cd /workspace/FuseLink/testvllm
.venv/bin/python pull_demo.py pull --protocol rdma --device mlx5_bond_0 --host 11.163.39.114 --info target-cross-rdma.json
```

需要重新启动源端时，在远端前台运行（先停止旧源进程）：

```bash
ssh 11.163.39.110
cd /workspace/FuseLink/testvllm
.venv/bin/python pull_demo.py target --protocol rdma --device mlx5_bond_0 --host 11.163.39.110 --info target-cross-rdma.json
```

看到 READY 后，本机刷新元数据再执行 pull：

```bash
scp 11.163.39.110:/workspace/FuseLink/testvllm/target-cross-rdma.json .
```

停止源端时，在源端终端按 Ctrl+C；对于后台进程，应先确认 PID 对应当前实验，再发送 SIGTERM。
源进程退出后，其地址和 JSON 即失效。本次验证未涉及 GPU 内存。

## 获取源码与结果

```bash
git clone --recurse-submodules https://github.com/shanli237/test-kv.git
cd test-kv
```

Mooncake 以子模块固定到 v0.3.14。结果汇总见 [RESULTS.md](RESULTS.md)，原始日志保留在仓库根目录。运行时 target*.json 包含进程地址，只在源进程存活期间有效，不纳入版本管理。
