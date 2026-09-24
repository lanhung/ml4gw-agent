# 完整契约示例：aframe.detect

[可加载的完整 YAML](../examples/skill_contracts/aframe.detect.yaml) 是
[当前正式契约](../src/ml4gw_agent/skill_manifests/aframe.detect.yaml) 的副本，
包含输入 / 输出 schema、前置条件、验证、资源、风险、来源和说明；格式为
`schema_version: "1.0"`，技能版本 `0.2.0`，状态 `experimental`。

## 一次完整调用

先生成计划并通过 mock 执行，不需要模型或凭据：

```bash
uv run ml4gw-agent plan 'Run Aframe and AMPLFI on GW150914' --output /tmp/aframe-plan.json
uv run ml4gw-agent run-plan /tmp/aframe-plan.json --mode mock --runs-dir ./runs/example
```

计划将 `data.resolve_event → data.fetch → data.inspect → aframe.detect →
amplfi.pe → report.generate` 串联。Aframe 的输入示例（真实执行使用指定 revision）：

```json
{
  "strain_artifact": "${fetch_data.outputs.strain_artifact}",
  "ifos": ["H1", "L1"],
  "model_revision": "3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4",
  "device": "cpu",
  "seed": 0,
  "target_time": "${resolve_event.outputs.catalog_time}",
  "candidate_window_seconds": 2.0,
  "threshold": 0.0
}
```

引用由运行时解析为实际路径和 GPS 秒，然后才验证输入 schema。Aframe 只在
`inspect_data.outputs.quality_passed` 为真时运行。`threshold: 0.0` 是原始输出
阈值示例，不代表显著性；规划器通常从版本化校准表填入 FAR 对应的阈值及来源。

合法的最小输出形状如下（数值仅用于说明，明确标记模拟）：

```json
{
  "candidate_found": true,
  "candidate_times": [1126259462.4],
  "predicted_coalescence_time": 1126259462.4,
  "detection_statistic": 9.5,
  "output_artifact": "artifacts/run_aframe/aframe_outputs.hdf5",
  "simulated": true
}
```

真实产物含 Aframe 时序输出，格式与 Buoy 相容；运行记录另外保存校准、模型、
调用、验证、文件大小和 SHA-256。二进制文件不放进 MCP 返回值。

## 已执行的检查与文档声明

| 约束 | 当前执行位置与边界 |
|---|---|
| 参数名、类型、必填输出 | JSON Schema 在运行时检查；schema 默认值本身不会自动写入输入 |
| H1 / L1 顺序与采样率 | 适配器要求严格 `['H1', 'L1']`；与加载模型的采样率比较，拒绝静默重采样；schema 单独不能保证顺序或唯一性 |
| 应变、时间、长度 | strain HDF5 为无量纲应变、采样率 Hz、GPS 起点秒；读取器和数据检查验证有限性与长度，模型最小长度在执行时检查；仅靠数值不能证明物理单位或训练适用域 |
| 不可变模型 | 策略拒绝 `UNPINNED`；适配器记录加载 revision；契约的非空字符串约束不证明任意 revision 已经存在或经过评审 |
| 前置条件名称 | `aframe_compatible_input` / `pinned_model_revision` 是声明，具体检查写在策略和适配器里，不由名称动态运行 |
| 科学输出 | 检查非空、有限值、峰值在窗口内、目标时间偏移、校准 revision 一致；声明的文件必须存在并位于运行目录 |
| 候选与下游 | 无候选时跳过 AMPLFI；有候选时将预测合并时刻交给 AMPLFI；阈值与 FAR 的领域有效性另审 |
| 软件与模型交付 | `uv sync --extra buoy` 安装固定 Buoy 版本；上游负责正式发布、容器、模型、训练数据与分发许可 |

缺少软件抛 `AdapterUnavailableError`；模型加载失败、采样率不匹配或非有限
输出抛 `AdapterError`；输出 schema / 产物失败为 `ValidationError`。运行记录
保留类型和原因，报告任务允许读取失败依赖。参考对照记录见
[Phase 1b 验收](PHASE1B_ACCEPTANCE_RUN_2026-09-03.md)，领域签字仍待确认。
