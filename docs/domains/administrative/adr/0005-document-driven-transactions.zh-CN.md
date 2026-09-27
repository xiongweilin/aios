# ADR 0005 — 文档驱动的组织事务

状态：**已接受，范围为记录的 isolated-staging；Admin PR #80 和 Kernel PR #99 已合并。本 ADR 记录 M8 decision boundary；M9 由 ADR 0006 及其 acceptance record 单独治理。**

## 决策

M8 在既有 Administrative governed-effect chain 上增加边界明确的 document-driven transaction preparation。Raw provider artifact 保持 immutable source evidence。任何 parser/OCR output 都是独立 immutable `DocumentRepresentation`，有自己的 extractor identity、version、digest、storage reference 和 page metadata。`EvidenceSpan` 可以指向产生它的 representation；历史 span 可保持 null。

Human confirmation 只 admit candidate request，不把 extracted fact 变成 truth。Transaction fact 继续是 claim，直到由 authoritative source 或显式记录、当前有效的 qualification assessment 进行 qualification。每个 qualification assessment 记录 input reference、rule identity、result、blocker、case 和 authority epoch。

首批 transaction case kind 严格为：

```text
procurement-request
invoice-ap-preparation
expense-reimbursement
```

只能创建边界明确的 ERP preparation effect：

```text
purchase_order.create_draft
purchase_order.confirm
vendor_bill.create_draft
expense_report.create
```

Kernel 拥有这些 capability 的 physical execution 和 independent readback。Bank transfer、payment execution、settlement、generic RAG、automatic approval 和第二个 workflow/controller authority 均不在范围内。

## 后果

- Parser failure 被分类为边界明确、安全的 error taxonomy，绝不能转成空的 successful representation。
- Representation identity 由 source artifact、extractor、extractor version 和 representation digest content-addressed。
- 每个 `(case_id, authority_epoch)` 只允许一个 immutable obligation set。
- Completion 把每个 expected business outcome 绑定到产生它的 effect；其他 effect 的 outcome 不能满足 obligation。
- ERP connector 使用 durable request/subject marker，reconcile ambiguous result，在无法获得精确 external identity 时 fail closed。
- M5–M7 migration、acceptance record 和 volume 继续作为 historical evidence，不被改写。

## 被拒绝方案

- 把 raw PDF 或 model output 当作 authoritative fact。
- 不保留 durable representation lineage，直接复用 parser text。
- 绕过 Kernel capability boundary，由 Administrative code 直接调用 Odoo 或 bank。
- 为 milestone 增加 generic document-understanding/RAG subsystem。
- 把 `expense-reimbursement` 做成实际 payment workflow。
