# 仓库迁移交接（2026-09-24）

软件交付可以本地验收；GitHub 仓库转移由维护者另行执行。本次未更改远端、
所有者、许可证或权重归属，未发布模型。工作区原有 `.gitignore`、README 和
`uv.lock` 改动保留。已移除计划中确认的根目录异常 `out,tuple(y.shape)…` 终端输出文件。

## 接收方复现

Python 3.10–3.12；本地 MCP 作业管理首版支持 Linux / macOS：

```bash
uv sync --locked --group dev --extra mcp --extra web
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pytest
uv run --no-sync python examples/mcp_mock_client.py --runs-dir ./runs/mcp-demo
```

只安装基础环境使用 `uv sync --locked --group dev`。可选科学依赖测试使用
`uv sync --locked --group dev --extra buoy` 后运行
`pytest tests/test_ldg_deepclean.py tests/test_deepclean_model.py --no-cov -rs`；
无需 GPU、凭据或在线科学数据。日常 CI 的 MCP / Web 接口任务显式安装对应
extra，科学依赖任务安装 Buoy / GWPy / Torch / ml4gw。

可选依赖缺失的测试必须显示安装命令与跳过原因；`httpx`、`scipy`、`astropy`
是开发测试的明确依赖，不能通过跳过掩盖缺失。覆盖率门槛保持 85%。

## 移交材料

| 材料 | 用途 |
|---|---|
| [README](../README.md)、[MCP 使用说明](MCP.md) | 安装、启动、mock 和真实分析配置 |
| [技能清单](SKILL_INTEGRATION.md)、[契约示例](SKILL_CONTRACT_EXAMPLE.md) | 上游接口和双方维护责任 |
| [模型来源表](MODEL_PROVENANCE_REVIEW.md) | 文件证据与独立确认的边界 |
| [路线图](ROADMAP.md)、[本期计划及验收](plan/P0_P1_IMPLEMENTATION_PLAN_2026-09-24.md) | 已接入功能、验收结果和后续工作 |
| `docs/acceptance/` | 历史真实运行记录；不是本次重跑结果 |
| `pyproject.toml`、`uv.lock`、`.github/workflows/tests.yml` | 可复现依赖与测试入口 |

## 外部步骤（尚未完成）

- 维护者指定目标组织、接收人、权限和转移时间；在 GitHub 确认目标可接收。
- 仓库未提供根目录 LICENSE；由权利人确定代码许可证，不能从上游项目推断。
- Fan / 模型权利人确认三份本地权重的归属与分发许可；审查非公开 O4 记录、
  原始内部路径和相关材料的可发布范围，不把哈希核验等同于授权。
- 接收方自行配置 CI secrets、节点和数据凭据，凭据不写入客户端工具参数。
- 维护者执行实际 GitHub 转移后检查重定向、CI、分支保护、权限、模型下载和
  文档链接；由接收方按上面命令验收并记录签字。

这些事项不阻塞离线 mock MCP，但未得到明确证据前不得标记外部确认完成。
