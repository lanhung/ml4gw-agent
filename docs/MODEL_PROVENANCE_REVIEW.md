# 模型来源核对表（2026-09-24）

这是仓库证据清单，不是训练归属或分发许可认证。下表保留现有元数据的原始
说法，不依据录音推断或重写 `trained_by`。缺少独立证据的归属待 Fan 确认。

| 模型 | 代码 / 版本证据 | 训练者 | 训练数据证据 | 导出 / 交付过程 | 评审状态 |
|---|---|---|---|---|---|
| GWAK S4 SimCLR embedder | [MANIFEST](../models/gwak/MANIFEST.json) 记载 ML4GW/gwak `7b9f58a`；尚缺完整 commit 与训练运行关联 | 现有字段称 `fan.zhang on the CIT LDG cluster`；无独立训练日志佐证，待 Fan 确认 | [训练配置](../models/gwak/train_config_S4_SimCLR_multiSignalAndBkg.yaml) 声明 O4 MDC background 路径、多类模拟信号、4096 Hz、双探测器；缺数据清单 / 校验和 / 实际使用区间 | 已有 TorchScript 文件和哈希；[历史记录](PHASE2_GWAK_RUN_2026-09-03.md) 描述导出与配对实验；缺原 checkpoint、导出脚本 / 命令 / 环境 | 文件一致性已核验；训练者、训练数据、正式配对、高通和步长待 Fan / 领域作者确认 |
| GWAK background NF metric | 同一 manifest 声明 `7b9f58a`；缺单独训练运行版本 | 同上字段覆盖整组模型；不能证明两个权重由同一人训练，待 Fan 确认 | 名称和 manifest 称 background-only；现有 SimCLR 配置不等于 NF 的训练数据证据，缺专属配置 | TorchScript + 哈希；CPU float64 行为记载于历史适配记录；缺原 checkpoint 与导出链 | 与 embedder 的配对是已有经验选择，未得到上游正式确认 |
| DeepClean H1 60 Hz | [训练记录](../models/deepclean/H1_60Hz/training_record.json) 引用 deepcleanv2 60 Hz 配方；本仓库 [模型实现](../src/ml4gw_agent/adapters/deepclean_model.py) / [训练脚本](../scripts/deepclean_train.py)；缺精确上游 commit | 记录仅称 self-trained stand-in；未具名，待 Fan 确认训练者和运行责任人 | H1 strain + mains witness；训练 GPS 1421344000–1421348096，留出至 1421349120；训练文件 SHA-256 `9e42008a8d16256b74efd2e557a9f195f81293ffe65fd33add5e490875abbfbc`，原数据未随仓库交付 | 权重、配置、[history](../models/deepclean/H1_60Hz/history.json)、训练耗时和指标在仓库；缺训练环境 / 精确代码关联及正式模型交付签字 | [support 表](../src/ml4gw_agent/calibration/deepclean_support.json) 含广泛 O4 适用区间与 stand-in 标记；“Reviewed”字样不构成领域签字，适用区间与分发权限待确认 |
| Aframe / AMPLFI | Buoy 0.6.1；历史验收固定 HF revision `3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4` / `8b97d2f8459d04924cb010dfee0262260bf3da80` | 上游模型；本仓库无独立训练归属认证 | 依上游模型说明和领域评审，不从 agent 验收推断训练数据 | 运行时从上游固定 revision 加载；[Buoy 对照证据](PHASE1B_ACCEPTANCE_RUN_2026-09-03.md) | 有软件执行与对照记录；本项目领域签字待确认 |

本次重新核对的本地文件（2026-09-24；仅证明与记录一致）：

| 文件 | SHA-256 |
|---|---|
| `models/gwak/embedder_S4_SimCLR_multiSignalAndBkg.pt` | `f775aed557370a77b1fb0568b1e45015a6482bb7213832782d54e05979620c6f` |
| `models/gwak/metric_NF_onlyBkg.pt` | `a0c755adebfadb678dd4bcd7c190c57007d089ac4281f989e0a0ebef62bb3812` |
| `models/deepclean/H1_60Hz/deepclean.pt` | `b1960171f6b1b8480f6a34926e357e1e7353b18d5744ea32ba732bd5ad1d897f` |

维护者待办：Fan 确认训练者与原始 checkpoint → 补全训练数据 / 代码 / 导出链 →
领域作者确认配对和适用范围 → 权利人确认模型与非公开数据相关材料的分发权限。
审核人、日期和原始证据尚未提供，因此这些外部项保持待确认。
