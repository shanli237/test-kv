# 真实 vLLM GPU KV 跨机传输验证

2026-11-06，prefill=.110，decode=.114；Qwen2.5-0.5B-Instruct，vLLM 0.31.0，TE CUDA13 0.3.14。
模型权重两端 SHA256 均为 `fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe`，来源与其他文件哈希见 vllm_lab/model-manifest.json。

## 验证结论

- 14 个 HTTP 请求成功：3 个 decode 直接完整推理对照，3 个 P/D 对照，8 个并发度 2 的 P/D 请求。
- 输入长度 22、1673、6665 token 的三组对照，生成文本逐字一致。
- 捕获 11 次 TE batch WRITE，全部 rc=0，合计 217841664 字节（207.75 MiB）。
- 分片日志 source_location=cuda:0 / target_location=cuda:0，local_device_name=mlx5_bond_0 / peer_device_name=mlx5_bond_0。
- 这些是模型生成的真实 KV tensor，不是此前固定字节 CPU buffer。没有额外逐字节比较 GPU KV；使用生成输出一致性、connector 状态、TE 成功事件及 GPU 地址/位置日志交叉验证。

实际数据路径：.110 GPU0 HBM → .110 bond_0 → RDMA 网络 → .114 bond_0 → .114 GPU0 HBM。
控制侧由 decode 发起远端 KV 获取请求；数据侧为 prefill 的 batch_transfer_sync_write，不应标注为 RDMA READ。

## 配置与正确性范围

每端单 GPU，TP=1，BF16，KV cache 1 GiB，max-model-len=8192，eager，关闭 prefix caching，VLLM_BATCH_INVARIANT=1，实际 attention backend=FLASH_ATTN。
默认 FLASHINFER 配置曾产生一条短提示词输出不一致，原始失败对照保留在 20261106T080624Z。开启 batch-invariant 同时改变了 backend 后，三组样本均一致；未将变化归因于单一因素。
不是性能基准：首次请求约 34 秒，包含运行时初始化/JIT；详细日志、API hook 与 batch-invariant 都可能改变时延。

## 结果文件

- [放大时间序列图](timeline-detail.png)：聚焦有 KV 传输的时间段。
- [完整时间序列图](timeline.png) / [PDF](timeline.pdf)。
- [结构化汇总](summary.json)：TE WRITE 时延、字节数、返回码、正确性比较。
- requests.json：完整请求、模型响应、起止时间；HTTP 为完整响应延迟，非 TTFT。
- local-nics.jsonl / remote-nics.jsonl：两端 NIC 原始时间序列。
- prefill-trace/：TE API 事件；prefill.log / decode.log：GPU 注册、分片与请求调度记录。
- *-metrics-before.txt / *-metrics-after.txt：vLLM Prometheus 快照。

NIC 计数为全局流量，有背景任务；100 ms 采样不足以还原毫秒级瞬时峰值。
远端时间对齐通过 SSH 往返探测估计，半宽约 0.061 ms，不代表硬件时钟精确同步；采样读取窗口另有时间误差。
本轮 sampler 已退出；prefill/decode/proxy 服务保留运行，启动/停止见 vllm_lab/README.md。
