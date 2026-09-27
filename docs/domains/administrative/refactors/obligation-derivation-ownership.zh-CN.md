# Obligation derivation 所有权

本次 closure 后重构把 generic obligation contract 与 Administrative domain interpretation 分开，不改变任何已接受 execution semantics。

## 边界

`obligations.py` 只拥有可复用 obligation vocabulary、durable row、repository behavior、fulfillment record，以及用于历史 import 的 compatibility facade。

Domain interpretation owner：

- `onboarding_obligations.py`：employee-onboarding obligation derivation；
- `offboarding_obligations.py`：employee-offboarding、authority-revocation、continuity-transfer obligation derivation；
- `financial_obligations.py`：procurement、invoice/AP preparation、expense obligation derivation；
- `obligation_derivation.py`：只负责 fail-closed case-kind dispatch；
- `obligation_derivation_common.py`：domain derivation 共享的稳定 construction。

Execution code 从 owning domain module import derivation function。既有 caller 可以继续从 `obligations.py` import 历史名称；这些 function 只是 thin lazy forwarding wrapper，不包含 case 或 operation interpretation。

## Invariant

- 无 database migration；
- 不改变 obligation、requirement、governance-basis、authorization、effect、outcome 或 fulfillment identity；
- 不改变已声明 obligation tuple order 或 migration `0032` sequence semantics；
- 不改变 expected postcondition 或 fulfillment kind；
- 不改变 authority epoch、approval、completion、responsibility discharge、Kernel contract、capability contract 或 provider behavior；
- 历史 M5/M6/M7/M8/M9 acceptance evidence 和 tag 保持 immutable。

目标是 responsibility ownership，而不是缩小文件：generic persistence 保存冻结 obligation graph；每个 domain 继续负责决定该 graph 的含义。
