# ADR 0007 — World Runtime 语义所有权

状态：accepted  
日期：2026-09-20

## 背景

Administrative 需要一个通用 durable runtime owner，同时不能把 Administrative facts、policy、obligation、outcome semantics 或 completion 移入该 runtime。

## 决策

当前所有权：

```text
semantic-language
  跨领域含义和 non-substitution rules

world-runtime
  persistent agency/runtime primitives
  responsibility / Work / Run
  governance / Decision / Mandate / Authorization
  provider execution / durable attempts / reconciliation
  generic epistemics / cognition / memory / strategy

administrative-orchestrator
  Administrative facts / policy / authority
  obligations / business effect intent
  authoritative read-back
  ConfirmedOutcome / completion / reopen
```

Administrative 把边界明确的 domain effect 编译为 Runtime responsibility/authority/execution object，但不会委托 domain Outcome semantics。

Provider success 仍然与 Administrative completion 分离。

## 后果

- 新 Runtime feature 必须由跨领域 runtime invariant 证明合理，而不是为了 Administrative implementation convenience；
- Autonomous Development 作为另一个 external Domain Controller 集成，而不是把 Git/build/canary/release semantics 移入 Runtime core；
- Administrative 继续持有 authoritative read-back、domain Outcome、completion 和 reopen semantics。
