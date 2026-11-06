#!/usr/bin/env bash
set -euo pipefail
cd /workspace/FuseLink/testvllm
role=${1:?prefill or decode}
case "$role" in
  prefill) host=11.163.39.110; port=18910; kv_role=kv_producer ;;
  decode) host=11.163.39.114; port=18920; kv_role=kv_consumer ;;
  *) exit 2 ;;
esac
export CUDA_VISIBLE_DEVICES=0
export VLLM_HOST_IP="$host"
export VLLM_MOONCAKE_BOOTSTRAP_PORT=18998
export MC_TE_FILTERS=mlx5_bond_0
export MC_LOG_RDMA_SLICE_AFFINITY=1
export GLOG_v=1
export VLLM_LOGGING_LEVEL=DEBUG
export VLLM_BATCH_INVARIANT=1
export HF_HUB_OFFLINE=1
export VLLM_LAB_TRACE_DIR="$PWD/vllm_lab/logs/$role-trace"
export PYTHONPATH="$PWD/vllm_lab/trace_hook${PYTHONPATH:+:$PYTHONPATH}"
exec .venv-vllm/bin/python -m vllm.entrypoints.cli.main serve \
  "$PWD/vllm_lab/models/Qwen2.5-0.5B-Instruct" \
  --served-model-name qwen-kv-lab --host "$host" --port "$port" \
  --tensor-parallel-size 1 --dtype bfloat16 --max-model-len 8192 \
  --max-num-seqs 8 --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.1 --kv-cache-memory-bytes 1073741824 \
  --enforce-eager --no-enable-prefix-caching \
  --kv-transfer-config "{\"kv_connector\":\"MooncakeConnector\",\"kv_role\":\"$kv_role\",\"kv_connector_extra_config\":{\"mooncake_protocol\":\"rdma\",\"device_name\":\"mlx5_bond_0\",\"num_workers\":4}}"
