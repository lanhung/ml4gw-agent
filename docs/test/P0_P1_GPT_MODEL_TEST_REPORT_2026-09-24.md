# P0/P1：CLIProxy 多 GPT 模型测试报告

日期：2026-09-24。对应[实施计划](../plan/P0_P1_IMPLEMENTATION_PLAN_2026-09-24.md)。

使用相同场景的 GLM 补测见[GLM 全部可用模型测试报告](P0_P1_GLM_MODEL_TEST_REPORT_2026-09-24.md)，本报告保留原 GPT 成绩。

**本轮七个模型共 42 个场景，38 个通过、4 个失败（90.48%）；299/308 项断言通过。**
`gpt-5.5`、`gpt-5.6-luna` 和 `gpt-6-astra` 均为 6/6，其余四个模型均为 5/6。
全部模型都完成测试，没有重试或用旧结果替换本轮失败。

测试窗口为 **2026-09-24 06:45:23–06:55:24 UTC**，整体墙钟耗时 600.644 秒。
共发出 191 次聊天请求：190 次 HTTP 200，1 次 HTTP 408；没有本地传输超时。
所有 HTTP 200 响应的模型 ID 均与请求一致。

| 模型（原始结果） | 场景通过 | 断言通过 | 聊天请求 | 单模型耗时 / 秒 | 请求耗时中位数 / 秒 | 已报告 tokens |
|---|---:|---:|---:|---:|---:|---:|
| [gpt-5.5](../acceptance/p0-p1-2026-09-24/gpt-matrix/gpt-5.5.json) | 6/6 | 44/44 | 29 | 186.109 | 3.729 | 115,515 |
| [gpt-5.6-luna](../acceptance/p0-p1-2026-09-24/gpt-matrix/gpt-5.6-luna.json) | 6/6 | 44/44 | 25 | 138.683 | 4.756 | 106,567 |
| [gpt-5.6-sol](../acceptance/p0-p1-2026-09-24/gpt-matrix/gpt-5.6-sol.json) | 5/6 | 43/44 | 26 | 175.093 | 4.381 | 149,331 |
| [gpt-5.6-terra](../acceptance/p0-p1-2026-09-24/gpt-matrix/gpt-5.6-terra.json) | 5/6 | 38/44 | 24 | 146.417 | 4.143 | 94,933 |
| [gpt-6-astra](../acceptance/p0-p1-2026-09-24/gpt-matrix/gpt-6-astra.json) | 6/6 | 44/44 | 29 | 240.317 | 5.321 | 112,227 |
| [gpt-6-luna](../acceptance/p0-p1-2026-09-24/gpt-matrix/gpt-6-luna.json) | 5/6 | 43/44 | 28 | 125.122 | 3.197 | 207,593 |
| [gpt-6-sol](../acceptance/p0-p1-2026-09-24/gpt-matrix/gpt-6-sol.json) | 5/6 | 43/44 | 30 | 142.978 | 3.797 | 151,858 |

单模型耗时含 MCP 启停与请求处理，不含等待并发槽位的时间；因两模型并行，
各行耗时相加不等于总墙钟时间。各模型 reasoning / temperature 使用代理默认值。
usage 合计 **938,024 tokens**：输入 916,217、输出 21,807；输入中已包含
491,776 个代理报告的缓存 tokens。HTTP 408 未返回 usage，未估算该请求用量。

| 模型 | Buoy | Aframe→AMPLFI | Aframe＋GWAK | 非法请求 | 零预算 | 忙与取消 |
|---|---|---|---|---|---|---|
| gpt-5.5 | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| gpt-5.6-luna | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| gpt-5.6-sol | 通过 | 通过 | 失败：否定词 | 通过 | 通过 | 通过 |
| gpt-5.6-terra | 通过 | 通过 | 失败：HTTP 408 | 通过 | 通过 | 通过 |
| gpt-6-astra | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| gpt-6-luna | 通过 | 失败：Buoy 路由 | 通过 | 通过 | 通过 | 通过 |
| gpt-6-sol | 通过 | 通过 | 失败：否定词 | 通过 | 通过 | 通过 |

四个失败场景归为三类，详情和复现见下文。七个模型的非法请求、预算拒绝及
忙/取消场景全部通过。矩阵命令按预期返回退出码 `1`，因为存在未通过场景。

已复核 **28 个作业记录**：21 个 mock 分析落盘完成、7 个延迟夹具作业取消；
所有作业均为终态。21 份完成 manifest 对应的 **135 个产物**全部通过路径范围、
大小与 SHA-256 检查，其中包括 HTTP 408 场景已落盘但 GPT 未读回的 7 个产物。
矩阵内原有“根据成功 get_run 复核”的统计为 20 份 manifest / 128 个产物；
补充的全部落盘复核没有改变端到端场景的通过/失败判定。
[完整落盘复核结果](../acceptance/p0-p1-2026-09-24/gpt-matrix/post-verification.json)。


## 测试对象与方法

本轮从本机 CLIProxy 的 `http://127.0.0.1:8317/v1/models` 读取模型列表，
选中其中全部七个文本 GPT 模型，并对每个模型重新执行同一套六场景测试。
之前 `gpt-6-sol` 的单模型结果保留为历史证据，不用于填补本轮结果。
模型名称按代理公布及响应返回的 ID 记录；没有独立核实代理背后的模型别名映射。

调用链为：

```text
CLIProxy 中的 GPT（真实网络调用）
  → 模型自主生成 function/tool calls
  → 官方 MCP Python 客户端（stdio）
  → ML4GW Agent 五个 MCP 工具
  → 确定性规划器、策略/预算检查、本地 worker
  → mock 报告、运行记录与科学格式产物
```

测试程序根据 MCP 实际返回值判定结果，不采纳 GPT 自行声明的“通过”。
服务内的规划器仍是本期计划指定的确定性规划器；GPT 负责外部工具调用和结果
读取。本轮未启用真实科学分析、未运行 GPU 模型，也未替代领域科学验收。

| 控制项 | 本轮设置 |
|---|---|
| Python / MCP SDK | 3.12.14 / 2.2.0 |
| GPT 接口 | `/v1/chat/completions`，非流式，原生工具调用 |
| 工具来源 | 每个场景由官方 MCP 客户端实时发现五个工具及输入 schema |
| 提示词 | 各模型相同，包含中文、英文任务与明确的负向测试请求 |
| 每模型重复次数 | 1；六个场景均使用独立会话和服务目录 |
| 并发 | 最多两个模型并行；同一模型的六个场景串行 |
| 单次 HTTP 超时 | 90 秒 |
| 每场景上限 | 16 次模型请求，每次 `max_tokens=2500` |
| 采样与推理参数 | 未传 temperature、seed 或 reasoning_effort，沿用代理默认值 |
| 客户端重试、模型回退 | 均未启用；保留每次失败，不重跑以替换本轮成绩 |
| 科学执行 | mock；服务未开启 `--allow-real` |
| 作业产物复核 | 独立读取完成的 manifest，检查文件路径范围、大小及 SHA-256 |

本轮每个模型有 44 项断言。模型响应措辞不要求一致，成功路径的技能序列必须
与目标流程一致，最终报告须明确说明 mock / SIMULATED / 模拟含义。

## 六个场景

| 场景 ID | 请求与核验内容 | 预期 |
|---|---|---|
| `buoy` | 查询技能后，默认分析 GW150914，读取报告和产物 | 12 项技能；3 项任务完成；5 个产物 |
| `aframe_amplfi` | 对 GW150914 运行 Aframe→AMPLFI | 6 项任务完成；7 个产物 |
| `aframe_gwak` | 对 GW150914 运行 Aframe＋GWAK＋reconcile | 8 项任务完成；7 个产物 |
| `invalid_requests` | 未知计划、未知作业、非法 ID、real 未启用、注入 `config.allow_real` | 五次实际调用均被拒绝；不启动有效作业 |
| `budget` | 在零 GPU-hour 配额下计划 mock CUDA 分析，并尝试启动 | 计划预算不允许；启动返回 `BUDGET_EXCEEDED` |
| `busy_cancel` | 启动后重复启动，再取消、查询、再次取消 | `SERVICE_BUSY`；三次取消相关结果均为 `cancelled` |

`busy_cancel` 使用仅改变 worker 启动时间的测试夹具：在独立服务进程中给
`run-plan` worker 增加 300 秒延迟，确保 GPT 下次调用时作业仍活跃。
进程组取消和状态持久化仍使用产品实现。其余五个场景调用未修改的服务。
因此该场景验证接口和作业生命周期，不代表真实科学计算已完成中断验收。

## 发现的问题

### 规划器把否定表达中的 AMPLFI 关键词当成执行请求

`gpt-5.6-sol` 在 `aframe_gwak` 场景调用 `plan_analysis` 时加入了
“不要运行 AMPLFI 参数估计”，`gpt-6-sol` 加入了“不需要 AMPLFI 参数估计”。
两次服务返回的计划均包含 `amplfi.pe`，实际执行了 9 项任务、生成 9 个产物，
而预期是 8 项任务、7 个产物。
两例的 `expected_skills` 断言失败；HTTP、执行状态、报告和产物检查均正常。
两个模型都在最终回复中指出了多执行 AMPLFI 的异常，但没有在调用启动工具
前阻止它。上次 `gpt-6-sol` 单轮通过、本轮出现不同改写并触发缺陷，也说明
单次通过不能证明这种自然语言接口的稳定性。

已脱离 GPT 独立复现：基础请求不包含 AMPLFI 时生成预期任务图；在请求后
加上英文 `Do not run AMPLFI.` 或中文 `不要运行 AMPLFI 参数估计。`，均会
加入 `amplfi.pe`。原因是
[`BaselinePlanner._contains`](../../src/ml4gw_agent/planning.py) 采用子串匹配，
没有解析否定语义。[复现证据](../acceptance/p0-p1-2026-09-24/gpt-matrix/planner-negation-repro.json)
记录了三组输入、输出技能序列与源码哈希，未执行科学分析。

待处理：规划器支持明确的排除约束或正确处理否定表达，并在启动前核对返回的
任务图是否满足请求约束。本轮为保持各模型的测试条件一致，未修改产品规划器。

### CLIProxy 返回 HTTP 408，中断模型会话

`gpt-5.6-terra` 的 `aframe_gwak` 场景在计划和启动成功之后，第三次 GPT 请求
收到 HTTP 408；代理响应耗时 4.143 秒。客户端记录的是实际 HTTP 状态，
不是本地 90 秒计时器触发的 `ReadTimeout`。

落盘 manifest 显示 mock worker 的 8 项任务已经完成，但 GPT 没有成功发出
后续 `get_run` 并读回报告，故完整会话验收失败。该错误归为代理/上游请求
失败，具体哪一层产生 408 尚未确定。本轮未重试此请求，保留第一次观测结果。
后续可结合 CLIProxy 和上游日志排查；重试策略需单独记录首错与重试次数。

### Buoy 封装流程与独立 Aframe→AMPLFI 任务图不一致

`gpt-6-luna` 的 `aframe_amplfi` 场景把原请求改写为
`Run the Buoy event analysis pipeline for GW150914, using Aframe detection followed by AMPLFI parameter estimation.`，
因此规划器选择了 `data.resolve_event → buoy.analyze → report.generate`
三任务流程，实际生成 5 个产物。作业和报告都成功，唯独 `expected_skills`
与本场景要求的六任务分解流程不一致。

Buoy 本身封装了 Aframe 和 AMPLFI，因此这条失败属于**严格任务图验收不匹配**，
存在请求措辞与验收粒度的差异；不能据此认定模型不会调用这些能力。
后续用例可明确要求独立的 `aframe.detect` 和 `amplfi.pe` 节点，并在工具层
提供显式流程选择。本轮不改写提示词或预期任务图以调整成绩。

## 不适用的代理条目

代理列出的以下六项未纳入这套文本工具调用用例；它们的状态记为“不适用”，
不计入通过或失败分母。

| 模型 ID | 原因 |
|---|---|
| `gpt-image-1.5` | 图像生成模型，P0/P1 MCP 流程无图像生成任务 |
| `gpt-image-2` | 同上 |
| `gpt-image-2.5` | 同上 |
| `gpt-image-2.5-flare` | 同上 |
| `gpt-image-2.5-sunburst` | 同上 |
| `codex-auto-review` | 专用审核条目，不属于本轮通用文本 GPT 测试对象 |

## 证据与复现

- [本轮机器可读汇总](../acceptance/p0-p1-2026-09-24/gpt-matrix/summary.json)：模型清单、排除原因、
  参数、脚本 SHA-256、各模型统计及产物复核结果。
- [完整执行日志](../acceptance/p0-p1-2026-09-24/gpt-matrix/matrix.log)保留每次工具调用与场景判定。
- [全部模型的测试入口](../../scripts/evaluate_mcp_gpt_matrix.py)；
  [单模型六场景执行器](../../scripts/evaluate_mcp_gpt.py)。
- 各模型的 JSON 保存每次 GPT 请求的 HTTP 状态、耗时、用量、响应模型名、
  工具调用参数与结果摘要、逐项断言、最终回复和完整会话的本机路径。
- 完整会话和实际产物位于 `runs/mcp-gpt-matrix/<model>/<timestamp>/`，
  已被 git 忽略；API 密钥不写入报告、会话或摘要。
- [上一次单模型测试记录](../acceptance/p0-p1-2026-09-24/cliproxy-gpt.json)保留独立时间与结果；
  其中一次取消夹具导入失败及修正记录，不并入本轮的成功/失败统计。

在仓库根目录执行，`--output-dir` 必须为空，防止覆盖前次结果：

```bash
uv sync --locked --extra mcp --group dev
uv run --no-sync python scripts/evaluate_mcp_gpt_matrix.py \
  --base-url http://127.0.0.1:8317/v1 \
  --proxy-config /absolute/path/cli-proxy/config.yaml \
  --workers 2 \
  --output-dir runs/mcp-gpt-matrix-new
```

也可设置 `ML4GW_LLM_API_KEY` 并省略 `--proxy-config`。脚本从配置中只读取
客户端 `api-keys`；不会更改代理配置。单独检查某模型或某场景：

```bash
uv run --no-sync python scripts/evaluate_mcp_gpt.py \
  --model gpt-6-astra \
  --proxy-config /absolute/path/cli-proxy/config.yaml \
  --case buoy \
  --output runs/mcp-gpt-astra-buoy.json
```

## 结果解释范围

这是六个固定场景、每模型一轮的接口验收。两模型共享代理并行调用，耗时受
上游排队、网络、缓存、回复长度和代理默认参数影响；不能据此给出一般性的
模型能力或稳定性排名。token 数是代理返回的 usage 字段，不等于费用账单。

本轮补充验证 P0/P1 的外部 agent 接口可用性。Python 3.10–3.12 离线测试矩阵、
覆盖率和科学依赖专项继续引用[原验收记录](../acceptance/p0-p1-2026-09-24/verification.json)，
不计作本轮重新执行。真实科学正确性、训练归属、分发许可和 GitHub 转移仍按
实施计划单独跟踪。

新增及调整的测试脚本已通过 `ruff check .` 和 `ruff format --check .`；
检查时全仓 153 个 Python 文件符合格式。报告链接、矩阵统计、脚本哈希、
凭据未写入证据及原始会话被 git 忽略均已核验。
