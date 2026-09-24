# P0/P1：GLM 全部可用模型测试报告

日期：2026-09-24。对应[实施计划](../plan/P0_P1_IMPLEMENTATION_PLAN_2026-09-24.md)。

**全部 11 个模型均已完成有效会话测试：55/66 个场景、473/484 项断言通过。**
这个汇总采用十个模型的首轮会话，加上 `glm-5-turbo` 限流后的唯一一次串行补测；
没有重跑或替换其余模型的任务图及参数错误。各条结果的来源见
[有效会话汇总](glm-retry-2026-09-24/effective-summary.json)。
`glm-4.5-air`、`glm-4.6`、`glm-5.1`、`glm-5-turbo`（补测）均为 6/6。

**首轮覆盖全部 11 个已列出模型、66 个场景：49 个通过，17 个未通过；434/484 项断言通过。**
未通过项包括 6 个默认任务图不匹配、5 个正常流程中的参数错误，以及 6 个在首个请求被 HTTP 429 限流的场景。
首轮获得模型响应的 10 个模型共 60 个场景，严格判定为 **49/60**；限流本身不能用于评价工具调用能力。

正式矩阵时间为 `2026-09-24T07:24:08.632600+00:00` 至 `2026-09-24T07:45:01.213405+00:00`，墙钟耗时 1252.580 秒。
共 265 次聊天请求：259 次 HTTP 200、6 次 HTTP 429，没有本地传输超时；所有 HTTP 200 响应的模型 ID 与请求一致。
接口累计报告 **1,729,801 tokens**，其中输入 1,654,315、输出 75,486；缓存命中输入 1,008,337 已包含在输入量中，不重复相加。限流请求未返回用量。

## 首轮逐模型结果（保留原始成绩）

| 模型（原始结果） | 场景通过 | 断言通过 | 请求数 | 耗时 / 秒 | 请求中位数 / 秒 | 已报告 tokens |
|---|---:|---:|---:|---:|---:|---:|
| [glm-4.5](glm-matrix-2026-09-24/glm-4.5.json) | 5/6 | 43/44 | 25 | 285.921 | 7.636 | 128,595 |
| [glm-4.5-air](glm-matrix-2026-09-24/glm-4.5-air.json) | 6/6 | 44/44 | 25 | 109.174 | 2.065 | 120,644 |
| [glm-4.6](glm-matrix-2026-09-24/glm-4.6.json) | 6/6 | 44/44 | 26 | 279.703 | 7.397 | 158,565 |
| [glm-4.7](glm-matrix-2026-09-24/glm-4.7.json) | 5/6 | 43/44 | 26 | 284.086 | 7.901 | 162,122 |
| [glm-5](glm-matrix-2026-09-24/glm-5.json) | 5/6 | 43/44 | 25 | 144.004 | 3.431 | 186,245 |
| [glm-5-turbo](glm-matrix-2026-09-24/glm-5-turbo.json) | 0/6 | 5/44 | 6 | 4.978 | 0.120 | 0 |
| [glm-5.1](glm-matrix-2026-09-24/glm-5.1.json) | 6/6 | 44/44 | 24 | 274.056 | 7.499 | 108,173 |
| [glm-5.2](glm-matrix-2026-09-24/glm-5.2.json) | 5/6 | 43/44 | 26 | 208.067 | 5.209 | 200,441 |
| [glm-5.3](glm-matrix-2026-09-24/glm-5.3.json) | 4/6 | 42/44 | 27 | 293.763 | 9.528 | 217,288 |
| [glm-5.3-flash](glm-matrix-2026-09-24/glm-5.3-flash.json) | 3/6 | 41/44 | 28 | 388.346 | 11.564 | 224,812 |
| [glm-5.3-flashx](glm-matrix-2026-09-24/glm-5.3-flashx.json) | 4/6 | 42/44 | 27 | 180.708 | 5.600 | 222,916 |

限流模型的低耗时表示请求很快被拒绝，不是模型推理速度。

| 模型 | Buoy | Aframe→AMPLFI | Aframe＋GWAK | 非法请求 | 预算 | 忙/取消 |
|---|---|---|---|---|---|---|
| glm-4.5 | 任务图不符 | 通过 | 通过 | 通过 | 通过 | 通过 |
| glm-4.5-air | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| glm-4.6 | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| glm-4.7 | 任务图不符 | 通过 | 通过 | 通过 | 通过 | 通过 |
| glm-5 | 任务图不符 | 通过 | 通过 | 通过 | 通过 | 通过 |
| glm-5-turbo | 限流 | 限流 | 限流 | 限流 | 限流 | 限流 |
| glm-5.1 | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| glm-5.2 | 任务图不符 | 通过 | 通过 | 通过 | 通过 | 通过 |
| glm-5.3 | 任务图不符 | 参数错误（已恢复） | 通过 | 通过 | 通过 | 通过 |
| glm-5.3-flash | 任务图不符 | 参数错误（已恢复） | 参数错误（已恢复） | 通过 | 通过 | 通过 |
| glm-5.3-flashx | 通过 | 参数错误（已恢复） | 参数错误（已恢复） | 通过 | 通过 | 通过 |

## 失败分析与证据

### 默认流程被改写

预期默认路由为 `data.resolve_event → buoy.analyze → report.generate`。以下模型在传给
`plan_analysis` 的文本中主动加入独立技能或参数估计步骤，规划器据此产生 6 或 9 个任务；
这些作业仍然完成，模拟报告和产物读取均正常，但 `expected_skills` 不通过。

| 模型 | 实际任务数 | 实际路线 |
|---|---:|---|
| `glm-4.5` | 9 | Aframe＋AMPLFI＋GWAK＋reconcile |
| `glm-4.7` | 6 | 独立 Aframe→AMPLFI |
| `glm-5` | 9 | Aframe＋AMPLFI＋GWAK＋reconcile |
| `glm-5.2` | 9 | Aframe＋AMPLFI＋GWAK＋reconcile |
| `glm-5.3` | 6 | 独立 Aframe→AMPLFI |
| `glm-5.3-flash` | 9 | Aframe＋AMPLFI＋GWAK＋reconcile |

[独立规划复现](glm-matrix-2026-09-24/planner-routing-repro.json)使用同一个确定性规划器：
简短默认分析请求得到 3 个 Buoy 任务，重放各模型实际生成的规划参数得到与实测一致的任务图。
该复现仅生成计划，不调用模型或执行科学任务。当前工具描述没有明确指出默认路由是 Buoy；
结合改写记录，建议补充这一契约并要求保留用户的流程范围。6 个独立任务与 Buoy 封装流程
在业务目的上可能相近，本报告沿用原 GPT 测试的严格任务图判定，没有因此放宽标准。

### 参数错误后恢复

以下场景中，模型在 `config` 内传入了禁止的 `mode` 字段；服务返回 `config.mode` 的
`extra_forbidden` 校验错误。模型随后删除该字段，保留顶层 `mode`，并完成正确任务图、
报告及产物读取。因正常流程要求 `no_tool_errors`，仍记为失败。

- `glm-5.3`：`aframe_amplfi`。
- `glm-5.3-flash`：`aframe_amplfi`。
- `glm-5.3-flash`：`aframe_gwak`。
- `glm-5.3-flashx`：`aframe_amplfi`。
- `glm-5.3-flashx`：`aframe_gwak`。

### GLM-5-Turbo 限流

该模型虽被 `/models` 列出，但首轮六个场景的第一次聊天请求均返回 HTTP 429、错误码
`1302`，没有模型响应、工具调用或作业。官方[错误码说明](https://docs.bigmodel.cn/cn/api/api-code)
将此码定义为账户速率限制。该结果属于接口可用性阻塞，不能推断模型不会完成这些任务。

在整个矩阵结束后等待 **100.969 秒**，用单模型、单请求流重新执行同样六个场景，
结果为 **6/6 场景、44/44 项断言通过**。补测共 25 次请求，均为 HTTP 200，
返回模型 ID 均为 `glm-5-turbo`，没有传输错误。六个场景累计耗时 272.283 秒
（不含模型发现），请求耗时中位数 7.248 秒，报告用量 147205 tokens。

补测的三个 mock 作业完成、一个取消，19 个产物独立校验通过。证据见
[补测结果](glm-retry-2026-09-24/glm-5-turbo.json)、
[补测摘要与核验](glm-retry-2026-09-24/summary.json)及
[日志](glm-retry-2026-09-24/retry.log)。未修改提示词、工具、断言或输出上限。
等待与降低测试并发后请求恢复，但本实验没有控制服务端状态，不能单独判定限流的具体原因。

加入补测后，11 个模型的非法请求、预算拒绝和忙/取消场景均通过。剩余 11 个
未通过场景就是上文的 6 个任务图不匹配和 5 个参数错误；五个参数错误均已由
模型自行纠正，相关分析最终完成。

### 文件与状态独立核验

正式矩阵共保留 40 个作业：30 个完成、10 个取消，全部已终止。
独立检查 30 份完成的 mock manifest、210 个产物，路径范围、大小和 SHA-256 全部一致。
66 份完整会话的断言重新计算结果与原记录一致；测试脚本和记录的产品模块哈希未变。
详情见[独立核验结果](glm-matrix-2026-09-24/post-verification.json)、
[矩阵摘要](glm-matrix-2026-09-24/summary.json)及[运行日志](glm-matrix-2026-09-24/matrix.log)。
原始错误全部保留；完整矩阵未使用旧结果替换，也没有在测试中修改规划器来消除失败。

补测另核验 3 份完成记录、19 个产物；预检查另核验 1 份完成记录、9 个产物。
全部 GLM 阶段共验证 **34 份完成的 mock manifest、238 个产物**，另有 11 个
取消作业。含预检查和补测，一共 295 次聊天请求，接口报告 1938942 tokens。

完整会话、原始报告、日志和科学产物也已归档到 `docs/test`：
[GLM 完整证据包](glm-evidence-2026-09-24.tar.gz)及
[逐文件 SHA-256 索引](glm-evidence-2026-09-24.index.json)。归档有 665 个文件，
981241 字节；已重新读取压缩包，逐个验证大小和哈希，并检查不含测试密钥。

## 范围与方法

使用用户指定的 `docs/key/glm.md`，连接智谱标准接口
`https://open.bigmodel.cn/api/paas/v4`。`GET /models` 返回 11 个 GLM 模型，
全部纳入测试，无排除项：`glm-4.5`、`glm-4.5-air`、`glm-4.6`、`glm-4.7`、
`glm-5`、`glm-5-turbo`、`glm-5.1`、`glm-5.2`、`glm-5.3`、
`glm-5.3-flash`、`glm-5.3-flashx`。“全部”指此次该凭据在此接口的模型列表，
不表示覆盖所有历史版本、其他平台或未开放的模型。

调用链为 **真实 GLM 工具调用 → 官方 MCP SDK 客户端 → 本地 stdio 服务 →
确定性规划器与 mock worker**。模型自行决定工具调用和参数；没有回放、
强制工具序列或模型回退。正式矩阵没有自动重试；限流后的独立补测另行存档，
不替换首轮成绩。科学执行固定为 mock，不能作为科学精度
或真实 GPU 执行的验收。

复用[GPT 测试](P0_P1_GPT_MODEL_TEST_REPORT_2026-09-24.md)的六个用户提示词、
系统提示词、五个 MCP 工具及 44 项判定。已逐项核对旧 GPT 原始会话中的提示词
和断言名称。模型间最多两路并发，同一模型的六个场景串行，每场景执行一次。
每次请求最多输出 2500 tokens，超时 90 秒，每场景最多 16 轮；温度和思考
参数均使用服务端默认值。
运行环境为 Python 3.12.14、官方 MCP SDK 2.2.0。

适配仅涉及测试客户端：支持从单行密钥文件读取鉴权、按 `glm-` 筛选模型，
并原样传回 GLM 响应中的 `reasoning_content`。该处理遵循官方
[OpenAI 兼容接口说明](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)
和[思考模式说明](https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode)。
本次未设置 `thinking` 或 `clear_thinking`，传回字段不等于显式开启保留式思考。
测试期间不修改产品规划器或服务；摘要记录脚本、场景及顶层产品模块的 SHA-256。

| 场景 | 判定要点 | 断言数 |
|---|---|---:|
| Buoy 默认流程 | 查询 12 项技能，准确生成 3 个任务，完成并读取模拟报告和产物 | 9 |
| Aframe→AMPLFI | 准确生成 6 个任务，完成并读取模拟报告和产物 | 8 |
| Aframe＋GWAK＋reconcile | 准确生成 8 个任务，完成并读取模拟报告和产物 | 8 |
| 五种非法请求 | 实际验证未知计划、未知作业、非法 ID、未开启 real、非法 `allow_real` 配置的拒绝 | 8 |
| 零 GPU-hour 预算 | 计划不获预算，实际启动返回 `BUDGET_EXCEEDED`，未启动作业 | 5 |
| 服务忙与取消 | 重复启动返回 `SERVICE_BUSY`，取消、查询及再次取消均正确 | 6 |

忙/取消场景在独立进程中使用 300 秒 worker 延迟夹具，确保能够取消活跃作业；
实际进程组取消逻辑不变，其余五个场景运行正常服务。通过与否依据真实 MCP
返回值和本地文件核验，不采用模型自行宣布的成绩。

## 兼容性预检查

完整矩阵前，单独运行了 `glm-5.3-flash` 的 Buoy 场景：接口和多轮工具调用
正常，分析完成并读取报告，但 `expected_skills` 未通过，最终为 0/1 场景、
8/9 项断言通过。模型将“默认流程”改写成包含 Aframe、AMPLFI、GWAK 和
reconcile 的请求，生成 9 个任务，与默认 Buoy 的 3 个任务不一致。

该预检查有 5 次请求、61936 个接口报告 tokens，单独保存在
[预检查结果](glm-preflight-2026-09-24/glm-5.3-flash.json)和
[日志](glm-preflight-2026-09-24/preflight.log)，不计入正式 66 个场景。
完整矩阵中该模型仍与其余模型一样，从独立服务重新运行六个场景；预检查
的失败不会被正式结果覆盖。

## 复现

在仓库根目录运行，密钥文件仅包含一行 token：

```bash
uv sync --locked --extra mcp --group dev
uv run --no-sync python scripts/evaluate_mcp_gpt_matrix.py \
  --base-url https://open.bigmodel.cn/api/paas/v4 \
  --key-file docs/key/glm.md --model-prefix glm- \
  --preserve-reasoning --workers 2 \
  --runs-dir runs/mcp-glm-matrix \
  --output-dir docs/test/glm-matrix-new
```

输出目录必须为空，防止覆盖旧证据。报告、逐模型断言和日志放在 `docs/test`；
完整会话及 mock 科学产物的工作副本放在被 git 忽略的 `runs/mcp-glm-matrix`，
其路径写入逐模型 JSON，本次交付另有上面的完整证据包。密钥文件已被 git 忽略；
密钥不作为模型上下文、命令参数或结果
写出。接口报告的 tokens 不是费用账单，单次测试的通过率也不代表长期可靠性。

单独复现限流模型的补测，可使用新的输出路径：

```bash
uv run --no-sync python scripts/evaluate_mcp_gpt.py \
  --base-url https://open.bigmodel.cn/api/paas/v4 \
  --model glm-5-turbo --key-file docs/key/glm.md --preserve-reasoning \
  --runs-dir runs/mcp-glm-retry-new \
  --output docs/test/glm-retry-new/glm-5-turbo.json
```

本轮只调整测试客户端兼容参数与证据记录；`ruff check .`、`ruff format --check .`
通过，154 个 Python 文件符合格式。未重跑完整离线测试矩阵或真实科学分析。
各提供方的默认推理策略、缓存及运行时负载不同，单次耗时与通过率不作为通用模型排名。
