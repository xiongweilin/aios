# P2 归档只读维护模型重放——手动运行契约

唯一 canonical GitHub Actions 工作流是 **BAA P2 Isolated Read-Only Maintenance Model Replay v1**。它在自托管 Windows runner 上执行，不连接实时 Keycloak、Odoo 或 World Runtime；模型端点限于已经存在的本机 loopback gateway。

## 手动选择

该 workflow 没有 push、pull_request 或 cron 触发，使用两项独立的 workflow_dispatch 输入：

- `run_mode=source_preflight_only`（**默认**）和 `approve_finite_model_sampling=no`（**默认**）：下载固定 P7 Actions ZIP，校验 SHA-256 和五窗口投影，执行离线测试，解析独立来源资格 JSON，并检测本机 gateway 与模型 catalog。**不会调用模型生成接口**。原始 artifact 如果过期则如实失败，不重造证据。
- `run_mode=model_sample` **且** `approve_finite_model_sampling=yes`：通过同一资格校验之后才执行冻结 P2 模型采样，上限 96 次不同模型调用；这可能产生费用，每次都必须单独批准。

不匹配的组合会被拒绝。不自动安排实验重试，不对业务系统写入。source-preflight 成功只说明接口准备好，**不等于真实模型已采样**。

## 首轮结果的版本边界

真实模型首轮已在 [AIOS run 37725010049](https://github.com/xiongweilin/aios/actions/runs/37725010049) 完成，执行的是 BAA `82370d7991eea9c288126610594a208efff06baa`：11 次物理调用、45 条制度记录；**没有 BAA 可委托前沿扩张**（C0/C1 三制度均 0/5；C2 三制度均 1/5）。[BAA 双语结果与无损机器归档](https://github.com/xiongweilin/BAA-Protocol/blob/main/experiments/p2-readonly-maintenance-model-v1-result.zh-CN.md) 已封存。

修改后的 workflow 固定较新的 BAA `3c9aec12cb261621cf79e4e693498af6f738647c`，仅修复冗余来源校验 JSON 的输出格式；**不重新计算或替代首轮结果**。以后的模型运行必须单独固定版本与费用证据。即使合格，结果仍只是相关归档读数的离线重放，不是在线随机化维护试验或真实 attention-risk 校准。
