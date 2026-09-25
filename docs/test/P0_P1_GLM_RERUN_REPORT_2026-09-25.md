# P0/P1：新契约下的 GLM 矩阵重跑报告（2026-09-25）

对应[实施计划第 6.6 节](../plan/P0_P1_IMPLEMENTATION_PLAN_2026-09-24.md)，
基线是 [2026-09-24 GLM 报告](P0_P1_GLM_MODEL_TEST_REPORT_2026-09-24.md)。

**有效成绩 65/66 场景、482/484 项断言，基线是 55/66、473/484。** 11 个场景修复，
1 个场景回归。回归的原因是新增的 `exclude_skills` 字段，已在提交后修复，
修复后尚未对该模型重跑。

## 运行条件

| 项目 | 值 |
|---|---|
| 时间 | 2026-09-25 02:32:50 至 02:50:33 UTC，矩阵墙钟 1063 秒 |
| 机器 | AutoDL GPU 节点，Python 3.12.12，官方 MCP SDK 2.2.0 |
| 代码 | 提交 `50a9983`；记录的 `planning.py`、`mcp_server.py`、`mcp_jobs.py` 哈希与该提交一致 |
| 接口 | 智谱标准接口，`/models` 列出同样 11 个模型，全部纳入 |
| 方法 | 与 9 月 24 日相同的提示词、系统提示词、六个场景、44 项断言；科学执行为 mock |
| 限流处理 | `glm-5-turbo` 首轮六个首请求均为 HTTP 429，等待 100 秒后单独串行补测一次 |
| 证据 | [矩阵摘要](glm-matrix-2026-09-25/summary.json)、[有效汇总](glm-matrix-2026-09-25/effective-summary.json)、[逐场景对比](glm-matrix-2026-09-25/compare-vs-2026-09-24.md)、[补测](glm-retry-2026-09-25/summary.json)、[规划器约束证据](planner-constraints-2026-09-25.json) |

首轮矩阵为 59/66：`glm-5-turbo` 的 6 个限流场景加 1 个回归。有效汇总只替换了
`glm-5-turbo` 一行，原 `summary.json` 未改。有效会话共 282 次请求，全部 HTTP 200，
无传输错误，接口报告 1,826,297 tokens。11 个模型每个都独立核验 3 份完成的 mock
manifest、19 个产物的路径、大小和 SHA-256，全部一致。证据中未发现密钥或
密钥形状的字符串。

## 逐模型结果

| 模型 | 9 月 24 日 | 9 月 25 日 | 变化 |
|---|---|---|---|
| glm-4.5 | 5/6 | 6/6 | 默认 Buoy 路由修复 |
| glm-4.5-air | 6/6 | 5/6 | Aframe＋GWAK 回归 |
| glm-4.6 | 6/6 | 6/6 | 不变 |
| glm-4.7 | 5/6 | 6/6 | 默认 Buoy 路由修复 |
| glm-5 | 5/6 | 6/6 | 默认 Buoy 路由修复 |
| glm-5-turbo | 6/6（补测） | 6/6（补测） | 不变；两次首轮都被限流 |
| glm-5.1 | 6/6 | 6/6 | 不变 |
| glm-5.2 | 5/6 | 6/6 | 默认 Buoy 路由修复 |
| glm-5.3 | 4/6 | 6/6 | 默认路由与 `mode` 位置均修复 |
| glm-5.3-flash | 3/6 | 6/6 | 默认路由与两处 `mode` 位置修复 |
| glm-5.3-flashx | 4/6 | 6/6 | 两处 `mode` 位置修复 |

## 两类旧失败都已消失

- **默认任务图不符（基线 6 个）：全部通过。** 模型从工具说明得知泛化请求默认走
  Buoy，没有再把"默认流程"改写成独立 Aframe / AMPLFI / GWAK 请求。
- **`mode` 放进 `config`（基线 5 个）：全部通过。** 三个分析场景共 35 次
  `plan_analysis` 调用，33 次显式把 `mode` 放在顶层，0 次放进 `config`。

模型也实际用上了新字段：17 次调用设置 `pipeline="decomposed"`，3 次设置
`pipeline="auto"`，3 次使用 `exclude_skills`。

## 新的回归：glm-4.5-air 的 Aframe＋GWAK

该场景共 6 次工具调用：

1. `plan_analysis`，提示词只有 `GW150914`，`config` 为
   `{"pipeline": "decomposed", "exclude_skills": ["amplfi.pe", "buoy_runner", "deepclean"]}`。
   `buoy_runner` 是配置参数名，`deepclean` 是工具族名，都不是技能名，服务端拒绝。
2. `list_skills`，取得 12 个技能名。
3. `plan_analysis`，改用正确技能名，但提示词仍只有 `GW150914`。泛化的分解请求
   得到 Aframe→AMPLFI，排除 AMPLFI 后只剩 5 项任务，没有 GWAK。
4. `plan_analysis`，提示词改为 "GW150914 with Aframe and GWAK detection and
   reconcile"，得到预期的 8 项任务。
5. `start_analysis` 启动第 4 步的计划。
6. `get_run` 读取完成的报告和产物。

分析最终正确完成，模型也在启动前核对了任务图，这正是契约要求的做法。但判定
要求正常流程没有工具错误、每个成功的计划都符合目标任务图，所以按原标准记为
失败，不放宽。

两个根因和对应修复（提交于本报告同一次提交）：

- **`exclude_skills` 的取值没有约束。** 工具 schema 只写了"字符串列表"，模型只能
  猜。现在 `AnalysisConfig.exclude_skills` 是 12 个注册技能名的枚举，MCP 客户端
  发现工具时就能看到全部合法值；填 `buoy_runner` 这类值会在参数校验阶段被拒绝，
  报错里列出全部合法名字。规划器对 CLI / Web 传入的未知名字也会列出合法值。
- **意图被移出了提示词。** 工具说明和服务 `instructions` 现在写明：要运行的分析
  必须写在 `prompt` 里，`config` 只能强制或收窄路线，永远不会增加工具。

## 限制

- 每个模型只跑一次。`glm-4.5-air` 9 月 24 日 6/6、这次 5/6，说明单次结果有波动，
  不能当作稳定的可靠性指标。
- 修复后没有重跑。用下面的命令只补测受影响的模型；新的输出不替换本次成绩：

  ```bash
  read -rs GLM_API_KEY && export GLM_API_KEY
  uv run --no-sync python scripts/evaluate_mcp_gpt.py \
    --base-url https://open.bigmodel.cn/api/paas/v4 \
    --api-key-env GLM_API_KEY --preserve-reasoning --model glm-4.5-air \
    --runs-dir runs/mcp-glm-fix-check \
    --output docs/test/glm-fix-check-<date>/glm-4.5-air.json
  ```

- GPT 矩阵尚未重跑。它依赖 CLIProxy，而 CLIProxy 不在这台 GPU 节点上；需要在
  CLIProxy 所在机器上用 `SKIP_GLM=1 DATE=2026-09-25` 运行
  `scripts/rerun_mcp_matrices.sh`。
- 科学执行全部为 mock；这些结果验证的是工具契约与调用行为，不是科学精度。
