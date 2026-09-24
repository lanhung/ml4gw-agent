# 本地 stdio MCP

使用官方 [Python SDK v2](https://github.com/modelcontextprotocol/python-sdk)，
依赖范围 `mcp>=2,<3`，解析版本保存在 `uv.lock`。首版提供本地 stdio 和单作业
执行，支持 Linux / macOS。默认 mock，无需 GPU、模型权重或凭据。

```bash
uv sync --locked --extra mcp --group dev
uv run --no-sync ml4gw-agent mcp --runs-dir ./runs/mcp
```

该命令等待 MCP 消息，不能当作交互式终端。stdout 只传协议，科学库输出与
worker 的 CLI 摘要写入每个作业的 `job.log`。正常断开、Ctrl-C 或 SIGTERM
都会取消活跃作业并保留记录。

## 客户端配置与演示

[配置模板](../examples/mcp-client.json) 中把 `/absolute/path/ml4gw-agent` 改成
本机检出路径。使用已同步环境的绝对 Python 路径，避免依赖客户端工作目录。
宿主支持的外层配置字段可能不同，启动命令与参数相同。

```json
{
  "mcpServers": {
    "ml4gw-agent": {
      "command": "/absolute/path/ml4gw-agent/.venv/bin/python",
      "args": ["-m", "ml4gw_agent", "mcp", "--runs-dir", "/absolute/path/ml4gw-agent/runs/mcp"]
    }
  }
}
```

官方 SDK 客户端可直接复现发现工具、规划、启动、查询和读取报告：

```bash
uv run --no-sync python examples/mcp_mock_client.py --runs-dir ./runs/mcp-demo
uv run --no-sync python examples/mcp_mock_client.py \
  --prompt 'Run Aframe and AMPLFI on GW150914' --runs-dir ./runs/mcp-demo
uv run --no-sync python examples/mcp_mock_client.py \
  --prompt 'Run Aframe and GWAK on GW150914' --runs-dir ./runs/mcp-demo
```

### 用 CLIProxy 中的 GPT 联调

[`scripts/evaluate_mcp_gpt.py`](../scripts/evaluate_mcp_gpt.py) 使用真实 GPT
请求，把官方 SDK 发现的五个 MCP 工具交给模型，再将模型生成的调用转发到本地
stdio 服务。服务内仍使用确定性规划器；科学执行固定为 mock。验收依据是实际
工具返回的任务图、状态、报告和产物，不采用模型自己声明的“测试通过”。

```bash
uv sync --locked --extra mcp --group dev
uv run --no-sync python scripts/evaluate_mcp_gpt.py \
  --base-url http://127.0.0.1:8317/v1 \
  --model gpt-6-sol \
  --proxy-config /absolute/path/cli-proxy/config.yaml \
  --output runs/mcp-gpt/evaluation.json
```

模型 ID 必须由该代理的 `/v1/models` 列出。可省略 `--proxy-config`，改用
`ML4GW_LLM_API_KEY` 环境变量；脚本只读取配置中的客户端 `api-keys`，不输出
密钥、不修改代理配置。完整会话、报告和产物保存在被 git 忽略的
`runs/mcp-gpt/<timestamp>/`，摘要写入 `--output`。

默认执行六个场景：Buoy、Aframe→AMPLFI、Aframe＋GWAK、五种非法请求、预算
拒绝，以及服务忙和取消。最后一项在独立服务进程中给 worker 增加 300 秒启动
延迟，以可靠触发活跃作业取消；进程组取消逻辑仍使用原实现，其余场景均使用
未修改的服务。可用 `--case buoy` 单独运行场景。测试需要代理可用并消耗模型
调用额度，不纳入离线 CI；没有模型回放或自动回退。

对代理列出的全部文本 GPT 模型运行同一套测试，可使用
[`scripts/evaluate_mcp_gpt_matrix.py`](../scripts/evaluate_mcp_gpt_matrix.py)：

```bash
uv run --no-sync python scripts/evaluate_mcp_gpt_matrix.py \
  --proxy-config /absolute/path/cli-proxy/config.yaml \
  --workers 2 --output-dir runs/mcp-gpt-matrix-new
```

每模型独立保存结果，输出目录须为空；失败不会被重试或替换。模型间最多两路
并发，同一模型的六个场景串行。图像生成和专用审核模型列为不适用。
方法、结果和限制见[多模型测试报告](test/P0_P1_GPT_MODEL_TEST_REPORT_2026-09-24.md)。

### 用 GLM 的全部可用模型联调

同一脚本也支持智谱的 OpenAI 兼容接口。按 `/models` 实时列出的 `glm-`
模型逐一运行六个场景，使用 `--key-file` 读取仅含一行密钥的本地文件：

```bash
uv run --no-sync python scripts/evaluate_mcp_gpt_matrix.py \
  --base-url https://open.bigmodel.cn/api/paas/v4 \
  --key-file docs/key/glm.md --model-prefix glm- \
  --preserve-reasoning --workers 2 \
  --runs-dir runs/mcp-glm-matrix \
  --output-dir docs/test/glm-matrix-new
```

`--preserve-reasoning` 将响应中的 `reasoning_content` 原样传回后续工具轮次，
遵循[GLM 思考模式的协议说明](https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode)。
该选项不设置 `thinking`、`clear_thinking` 或温度，仍使用提供方默认值。
默认每次最多输出 2500 tokens、请求超时 90 秒、每场景最多 16 轮，与 GPT
测试一致。脚本默认仍筛选 GPT，只有显式指定 `--model-prefix glm-` 才测试 GLM。

报告、逐模型结果和日志保存到 `docs/test`；完整会话和 mock 科学产物在被 git
忽略的 `runs/mcp-glm-matrix` 中，结果文件记录其路径。每次复现请用新的空输出
目录。密钥不进入命令参数、报告或会话；`--key-file` 与 `--proxy-config` 互斥。
本轮逐模型成绩与失败分析见[GLM 测试报告](test/P0_P1_GLM_MODEL_TEST_REPORT_2026-09-24.md)。

### 用新契约重跑与参考运行

`scripts/rerun_mcp_matrices.sh` 在有 CLIProxy 和 GLM 密钥的机器上一条命令重跑
两个矩阵，并用 `scripts/compare_mcp_matrices.py` 与 2026-09-24 基线逐场景对比。
`scripts/mcp_reference_agent.py` 是一个不含模型、严格按契约调用工具的本地
OpenAI 兼容服务，用来验证测试装置本身；其结果见
[参考矩阵报告](test/CONTRACT_REFERENCE_RUN_2026-09-24.md)，不作为模型成绩。

## 五个工具

| 工具 | 输入 | 主要返回 |
|---|---|---|
| `list_skills` | 无 | 注册表中 12 项完整契约、成熟度、mock / real 本机探测结果；可用性不等于某次分析通过 preflight |
| `plan_analysis` | `prompt`；顶层 `mode: mock / real`（默认 mock，不放在 `config` 内）；可选 `config`，含 `pipeline` 与 `exclude_skills` | `plan_id`、`route`、`excluded_skills`、有序 `skills`、原始 PlanSpec / 任务图、资源估计、预算决策、警告 |
| `start_analysis` | 保存的 `plan_id` | 立即返回 `job_id` 与状态；模式由保存记录决定，不接受任意计划、命令或路径 |
| `get_run` | `job_id` | 状态、逐任务结果 / 失败原因、Markdown 报告、产物路径 / 大小 / SHA-256、日志路径 |
| `cancel_run` | `job_id` | 终止进程组并保留记录；已结束作业保持原状态 |

### 路由契约

`mode` 是 `plan_analysis` 的顶层参数，`config` 只接受科学参数；把 `mode`
放进 `config` 会收到 `extra_forbidden` 校验错误。规划器按下面的固定规则选路，
返回值里的 `route` 和 `skills` 就是启动前要核对的内容：

| 请求 | `route` | 任务图 |
|---|---|---|
| 泛化请求，如 "Analyze GW150914"、"使用默认流程分析 GW150914" | `buoy` | `data.resolve_event → buoy.analyze → report.generate`（Buoy 内部运行 Aframe 和 AMPLFI） |
| 点名 Aframe、AMPLFI、GWAK、DeepClean 或数据质量 | `decomposed` | 独立技能 DAG；AMPLFI 只在 Aframe 报告候选后运行 |
| 目录问题，如 "What is the mass of GW150914" | `lookup` | `catalog.lookup`，不取应变、不跑模型 |

强制或收窄路线：

- `config.pipeline`：`auto`（默认，上表规则）、`buoy`（强制 Buoy；与 GWAK /
  DeepClean 请求或排除 Aframe / AMPLFI 冲突时拒绝）、`decomposed`（强制独立
  DAG；泛化请求得到 Aframe→AMPLFI）。
- `config.exclude_skills`：注册表技能名列表，如 `["amplfi.pe"]`。排除
  `buoy.analyze`、`aframe.detect` 或 `amplfi.pe` 会离开 Buoy 路线；排除
  `gwak.scan` 同时去掉 `analysis.reconcile`。未知技能名、与提示词正面请求
  冲突、或排除被请求技能的前置条件（AMPLFI 需要 Aframe）都会拒绝生成计划。
- 提示词中的否定表达（"do not run AMPLFI"、"without AMPLFI"、
  "不要运行 AMPLFI 参数估计"、"跳过 GWAK"）按子句识别，写入
  `excluded_skills`；计划若仍排入被排除的技能会失败关闭。提示词只排除前置
  条件（"run AMPLFI without Aframe"）时，前置条件仍会排入并给出警告。
  结构化的 `exclude_skills` 是权威通道；否定识别是启发式，见
  [`mentions()`](../src/ml4gw_agent/planning.py)。

复现记录：[`planner-constraints.json`](acceptance/p0-p1-2026-09-24/planner-constraints.json)，
由 `scripts/planner_constraints_check.py` 生成，覆盖 GPT / GLM 矩阵中失败的
否定和 Buoy 措辞用例以及结构化控制。

`config` 接受科学参数，如 `ifos`、`device`、`seed`、`window_seconds`、
`sample_rate`、`samples_per_event`、模型 revisions、FAR / 阈值、
`candidate_window_seconds`、`data_source` 和 Buoy 输出参数。完整 schema 随
工具发现返回。未知字段被拒绝，不能传 `allow_real`、审批、环境变量、执行器
或运行目录。首版固定使用确定性规划器和本地执行器。

工具拒绝通过 MCP `isError` 返回原因，例如 `UNKNOWN_PLAN`、`SERVICE_BUSY`、
`REAL_DISABLED`、`BUDGET_EXCEEDED`、`INVALID_ID`、`UNSAFE_PATH`。启动后的
科学前置条件失败为作业 `blocked`，逐任务保留缺模型 / 缺软件等原始原因；
执行失败为 `failed`。进程启动失败或异常退出分别记录 `PROCESS_START_FAILED`
或 `PROCESS_EXIT`。取消是 `cancelled`；重启发现未完成作业为 `interrupted`，
不自动重跑。已完成的记录可在重启后继续查询。

## 真实分析

```bash
uv sync --locked --extra mcp --extra buoy
uv run --no-sync ml4gw-agent doctor --mode real
uv run --no-sync ml4gw-agent mcp --runs-dir ./runs/mcp-real --allow-real
```

然后调用 `plan_analysis`：

```json
{
  "prompt": "Run Aframe and AMPLFI on GW150914",
  "mode": "real",
  "config": {
    "device": "cuda",
    "aframe_revision": "3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4",
    "amplfi_revision": "8b97d2f8459d04924cb010dfee0262260bf3da80"
  }
}
```

模型版本、科学前置条件、风险与预算沿用 runtime 检查。权限只来自启动选项：
`--allow-real`、`--approve-high-risk`、`--max-gpu-hours`、`--authorize-budget`；
MCP 不提供允许未固定模型的开关。预算是执行前估计检查，不是 GPU 计量限额。

LDG / NDS2 访问沿用现有环境凭据和可选依赖；在启动服务的环境中配置
`BEARER_TOKEN_FILE` / `X509_USER_PROXY` 等，不把凭据作为工具输入。
GWAK / DeepClean 可使用 `ML4GW_GWAK_MODEL_DIR` / `ML4GW_DEEPCLEAN_MODEL_DIR`
指向已审核模型目录。探测结果不保证在线模型、校准和凭据可用。
科学模型来源及待审核边界见 [来源核对表](MODEL_PROVENANCE_REVIEW.md)。

## 存储与边界

```text
runs/mcp/
  .service.lock
  plans/plan_<id>/plan.json
  plans/plan_<id>/metadata.json
  jobs/job_<id>/job.json
  jobs/job_<id>/plan.json
  jobs/job_<id>/job.log
  jobs/job_<id>/runs/run_<id>/run_manifest.json
  jobs/job_<id>/runs/run_<id>/report.md
  jobs/job_<id>/runs/run_<id>/artifacts/...
```

同一目录只允许一个服务实例，服务同时只执行一个作业。PlanSpec / RunManifest
保持原格式；保存模式与作业生命周期单独记录。仅可查询本服务目录内匹配
作业和计划身份的运行，拒绝路径穿越、符号链接和产物篡改。二进制只返回索引，
报告最多返回 256000 字符并标记截断。运行目录应由启动服务的用户独占管理。

本期不增加自动重规划或数据复用机制；固定 DAG 决定数据流，默认 Aframe
仍不消费 DeepClean 清洗产物。真实科学分析的历史验收不等于本次 mock 验收。
