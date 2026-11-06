# vLLM + Mooncake 双机 GPU KV 实验

## 当前部署

| 服务 | 地址 | GPU | 角色 |
|---|---|---|---|
| Prefill | 11.163.39.110:18910 | CUDA_VISIBLE_DEVICES=0 | kv_producer |
| Decode | 11.163.39.114:18920 | CUDA_VISIBLE_DEVICES=0 | kv_consumer |
| 实验代理 | 127.0.0.1:18900（.114 本机） | 无 | 上游 Mooncake proxy |
| Bootstrap | 11.163.39.110:18998 | 无 | 元数据查询 |

模型 Qwen2.5-0.5B-Instruct，BF16，TP=1，最大上下文 8192，单实例 KV cache 1 GiB，最多 8 个序列，eager 模式，prefix caching 关闭。两端固定 mlx5_bond_0。
vLLM 0.31.0、PyTorch 2.13.0+cu130、Mooncake CUDA13 0.3.14；详见 environment.json/environment-freeze.txt。

**数据面是 WRITE，不是 RDMA READ。** Decode 向 prefill 请求 KV，prefill 调用 batch_transfer_sync_write 将 GPU KV 写入 decode 已分配的 GPU block。仅控制语义是“获取远端 KV”。
已验证分片 source_location=cuda:0、target_location=cuda:0；GPU 显存注册，RDMA transport，网卡配对 bond_0→bond_0。

## 发请求

在 .114 机器运行：

```bash
curl http://127.0.0.1:18900/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen-kv-lab","messages":[{"role":"user","content":"简要解释 KV cache 的作用。"}],"temperature":0,"max_tokens":64}'
```

兼容 /v1/completions 和 /v1/chat/completions；已验证非流式 completion 及流式 chat。

## 启动、状态、停止

仓库根目录执行：

```bash
.venv-vllm/bin/python vllm_lab/control.py status all
.venv-vllm/bin/python vllm_lab/control.py stop all
.venv-vllm/bin/python vllm_lab/control.py start all
```

控制器通过 SSH 管理远端 prefill，只停止 PID/命令和进程组匹配的本实验服务。start 是后台启动，需等两端 /health 返回 200；代理日志出现 All prefiller instances are ready 后再发请求。
日志保存在 vllm_lab/logs/，重启追加记录；事件文件按 worker PID 区分。停止任一后端并重启后，应重启代理刷新 engine_id。
服务启动配置集中在 serve.sh。当前保留详细分片日志和 TE API trace，适合路径研究，性能评估时应另外控制日志开销。

## 数值稳定性

当前设置 VLLM_BATCH_INVARIANT=1，因此选择 FLASH_ATTN backend。
默认 FLASHINFER 下曾出现短提示词 P/D 与直接推理输出不同；日志保存在 experiments/vllm-pd/20261106T080624Z 和 logs/correctness-diagnostic.json。
开启 batch-invariant（同时切换 attention backend）后，22/1673/6665 token 三组提示词输出逐字一致。此结果不单独证明默认差异的唯一根因，也不宣称所有模型/请求 bitwise 一致。

## 监控与验证

```bash
.venv-vllm/bin/python vllm_lab/validate_pd.py
.venv/bin/python vllm_lab/render_validation.py experiments/vllm-pd/<本次UTC时间戳>
```

验证依次执行三组直接推理与 P/D 对照、8 个请求并发度 2 的负载。采集两端 NIC 时间序列、HTTP 请求/响应、connector/分片日志、prefill TE WRITE 事件，以及两端 /metrics 前后快照。
输出到新目录，不覆盖旧实验。图表的 HTTP 耗时为完整响应延迟，不是 TTFT；chat-stream-smoke.json 单独记录流式数据块抵达时间。

TE hook 通过服务专用 PYTHONPATH 加载 sitecustomize.py，只在设置 VLLM_LAB_TRACE_DIR 时启用，未修改全局 vLLM/Mooncake 包；记录注册范围与每次 batch WRITE 的字节数、描述符数、远端 session、API 起止时间和返回码。
应用 response.id 可以关联 connector DEBUG 日志中的 request/transfer ID；TE hook 的调用 ID 仅在该 worker 进程内有效，尚未建立结构化 request→TE-call 的完整关联，不能按时间邻近武断归属并发请求。

## 环境复现

两端已有 CUDA13 的 vLLM/PyTorch 环境，因此创建继承系统包的独立 venv，单独固定 TE 版本：

```bash
uv venv --system-site-packages .venv-vllm
uv pip install --python .venv-vllm/bin/python mooncake-transfer-engine-cuda13==0.3.14
```

environment-freeze.txt 是本机包版本快照，不保证任意基础镜像可直接完整重建。新机器需先准备匹配的 vLLM/PyTorch/CUDA 环境。
模型用 download_model.py 从 Qwen 的 ModelScope 仓库下载（Hugging Face 当时不可达），model-manifest.json 记录 URL、文件大小及 SHA256。模型文件与 venv 不纳入 Git；model-manifest.json 纳入。
将模型目录、serve.sh、control.py、trace_hook/、monitoring/telemetry.py 和 monitoring/sample_nics.py 同步到远端相同路径，再启动服务。

上游代理原样保存于 vendor/mooncake_connector_proxy.py，来源 vllm-project/vllm v0.31.0，SHA256 c3c8c8fb96e7f805bb9c2cef36391b1b1c0dcbd296d7d3156bc4b9dd4dfe9e41，保留 Apache-2.0 SPDX。它是上游实验代理，不是生产路由实现。

[最新验证报告](../experiments/vllm-pd/20261106T081631Z/REPORT.md)
