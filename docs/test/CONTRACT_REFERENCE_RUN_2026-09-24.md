# 新契约下的参考矩阵运行（2026-09-24）

对应[实施计划第 6.4 / 6.5 节](../plan/P0_P1_IMPLEMENTATION_PLAN_2026-09-24.md)。

**这不是模型重跑。** 本次执行环境没有 CLIProxy，也没有到 `open.bigmodel.cn`
的网络路径和 GLM 密钥文件，无法重跑 GPT / GLM 矩阵。为了让真正的重跑只度量
模型而不度量测试装置，这里用一个**按契约行事的确定性参考 agent**
（[`scripts/mcp_reference_agent.py`](../../scripts/mcp_reference_agent.py)）
替代模型，跑了与 GPT / GLM 矩阵完全相同的脚本、六个场景和 44 项断言。

参考 agent 是一个本地 OpenAI 兼容 HTTP 服务，不含任何语言模型。它每一轮只做
一件事：读取上一个工具返回值，按 `plan_analysis` 的契约发出下一次调用：

- `mode` 放在顶层，`config` 只放科学参数；
- Aframe→AMPLFI 场景用 `config.pipeline = "decomposed"` 强制独立 DAG；
- Aframe＋GWAK 场景用提示词否定句 "Do not run AMPLFI." **加上**
  `config.exclude_skills = ["amplfi.pe"]`，同时走词法和结构化两条排除通道；
- 启动前核对返回的 `route` 与 `skills`，不符则停止并报告；
- 五种非法请求、零预算、忙/取消场景按测试要求逐一调用并如实汇报。

## 结果

**6/6 场景、44/44 项断言通过**；独立核验 3 份完成的 mock manifest、19 个产物的
路径范围、大小和 SHA-256。证据：
[`summary.json`](contract-reference-2026-09-24/summary.json)（含脚本、场景和
产品模块哈希）、[`ref-contract-agent.json`](contract-reference-2026-09-24/ref-contract-agent.json)
（逐场景调用、返回值摘要、断言）。

| 场景 | 结果 | `plan_analysis` 返回 |
|---|---|---|
| Buoy 默认流程 | 通过 | `route=buoy`，3 项任务 |
| Aframe→AMPLFI（`pipeline=decomposed`） | 通过 | `route=decomposed`，6 项任务 |
| Aframe＋GWAK＋reconcile（否定句 + `exclude_skills`） | 通过 | `route=decomposed`，8 项任务，`excluded_skills=["amplfi.pe"]` |
| 五种非法请求 | 通过 | 五次均被拒绝，未启动作业 |
| 零 GPU-hour 预算 | 通过 | 预算不允许；启动返回 `BUDGET_EXCEEDED` |
| 服务忙与取消 | 通过 | `SERVICE_BUSY`；取消、查询、再取消均 `cancelled` |

这证明了两件事，也只证明这两件事：修改后的服务在原测试装置下仍能通过全部
断言；矩阵里失败的三类模型行为（否定被当作请求、Buoy 措辞路由、`mode` 位置）
在一个遵守新契约的客户端上都不再发生。它不能说明任何真实模型会遵守契约。

## 在你的机器上重跑真实矩阵

一条命令，输出到带日期的新目录并自动与 2026-09-24 基线逐场景对比：

```bash
CLIPROXY_CONFIG=/abs/path/cli-proxy/config.yaml bash scripts/rerun_mcp_matrices.sh
# 只跑其中一边：SKIP_GPT=1 或 SKIP_GLM=1；GLM 密钥文件默认 docs/key/glm.md
```

脚本依次：同步环境 → 重新生成规划器约束证据 → GPT 矩阵（CLIProxy）→
GLM 矩阵（智谱标准接口，`--preserve-reasoning`）→
[`scripts/compare_mcp_matrices.py`](../../scripts/compare_mcp_matrices.py)
生成 `compare-vs-2026-09-24.md/.json`，按模型 × 场景标出 fixed / regressed /
unchanged。测试脚本、提示词和断言与 9 月 24 日两轮矩阵完全一致，因此对比
是同条件的。限流（HTTP 429）的模型按原方法单独串行补测。

预期要看的三件事：

1. GPT 矩阵中 `gpt-5.6-sol`、`gpt-6-sol` 的 `aframe_gwak` 与 `gpt-6-luna` 的
   `aframe_amplfi` 是否从 FAIL 变为 pass；`gpt-5.6-terra` 的 408 是代理问题，
   与契约无关。
2. GLM 矩阵中 6 个"默认任务图不符"是否消失：模型现在能从工具说明知道泛化
   请求默认走 Buoy，并可核对 `route`。
3. GLM 5.3 系列 5 个"`mode` 放进 `config`"是否消失：工具说明和 schema 描述
   已写明 `mode` 是顶层参数。

对比结果出来后，把 `docs/test/*-matrix-<date>/` 提交入库并在计划文档第 6 节
追加一小节；原 6.2 / 6.3 成绩保持不改写。
