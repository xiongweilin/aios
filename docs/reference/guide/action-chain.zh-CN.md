# 工程行动链

> **迁移设计参考（非当前实施规范）**：本文由 [guide/engineering/action-chain.zh-CN.md](https://github.com/xiongweilin/guide/blob/511c073322c6b38ed2d36b32492836abf4d69b58/engineering/action-chain.zh-CN.md) 迁入，以保存原有工程分析。当前行为、权限、状态、契约和实现以 AIOS 现行 `docs/`、`contracts/`、源码与测试为准。概念框架以 [guide](https://github.com/xiongweilin/guide) 为准；本文不反向定义框架或现实本体。

[English](./action-chain.md) | [简体中文](./action-chain.zh-CN.md)

> 定位：当目的性有限行动者被实现成长期运行、会对现实产生可审计效果的系统时，为避免 correctness failure 而需要显式保持的工程语义。

框架层只要求：

`选择 / 行动 ≠ 现实效果 ≠ 反馈`

工程系统通常需要更细地展开。

## 1. 参考链

```text
当前边界 / 充分性依据
→ Decision
→ Governance basis / Commitment
→ Authorization
→ Execution attempt
→ Effect
→ Observation / authoritative read-back
→ Verification
→ Outcome
→ Completion / remaining obligation
→ Retain / Recovery / Revision / Reopen
```

这些位置不要求一一对应独立服务、类或表，但在实质相关时不能被静默压成同一状态。

## 2. 核心 non-substitution

`Candidate ≠ Decision`

`Decision ≠ Authorization`

`Authorization ≠ Execution`

`Execution success ≠ Effect`

`Effect ≠ Observation`

`Observation ≠ Verification`

`Effect ≠ Outcome`

`Outcome ≠ Completion`

`Completion ≠ long-term Responsibility discharge`

这些不是终极本体结论，而是当合并会造成真实错误时的工程边界。

## 3. Decision 不是 Authorization

一个系统可以已经形成选择，但当前 principal 仍没有对资源执行该动作的权限。因此存在合法状态：

`Decision = 1, Authorization = 0`

若合并两者，只能丢掉真实决定或凭空创造权限。

## 4. Effect 不是 Outcome

外部提供方可以成功产生现实变化，但目标属性仍未达到。例如部署已经发生，但产品指标没有改善：

`Effect = 1, Outcome = 0`

Provider 回执只能证明相称范围的执行 / 效果事实，不能自动证明领域结果。

## 5. 外部现实无法与本地事务原子提交

数据库事务不能让外部 API、设备、人、机器人、组织系统和本地 ledger 一起原子提交。

因此必须能够表示：

- 请求已发送但效果未知；
- 外部效果已发生但本地确认丢失；
- 部分成功；
- 效果可能发生但不能安全重放；
- 需要校正、补偿或恢复。

`transport idempotency ≠ effect idempotency`

## 6. 持久效果身份与幂等

高后果现实效果应具有稳定身份，以防超时后的重复执行、process restart 后丢失 effect attempt、并发 worker 同时 dispatch，以及同一 idempotency key 被重新绑定到不同 effect。

实际机制可以是 CAS、唯一约束、lease、dispatch fencing、outbox/inbox 等；guide 不规定唯一实现。

## 7. 观察与验证

Observation 应尽量来自现实侧，而不是简单复述执行器输出。

Verification 检查冻结的后置条件，例如对象身份、目标状态、不应变化的状态、重要副作用、作用范围与时间有效性。

`provider success ≠ verified reality`

## 8. Outcome 与 Completion

Outcome 是领域对现实效果的解释 / 资格判断。Completion 还可能要求义务完成、剩余风险可接受、长期监测结束、补偿完成或责任解除条件满足。

`Outcome ≠ Completion`

## 9. 恢复与重新打开

异常路径应保留 reconcile、仅在效果语义允许时 retry、compensate、rollback、stop、reauthorize 和 reopen boundary。

恢复成功也需要现实侧验证，而不能仅以恢复程序退出码判断。

## 10. 工程最小化原则

只有当一个区分同时满足以下条件时，才应提升成通用工程语义：

1. 多个实质不同领域都需要；
2. 合并会产生具体 correctness failure；
3. 含义跨领域稳定；
4. 不依赖特定 provider / workflow；
5. 不强迫领域 payload 进入通用内核。

AIOS 的 semantic promotion 规则是这一原则的一个具体实现。