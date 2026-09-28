# 语义所有权审计

Runtime 的精简目标是“零重复 semantic authority”，而不是“零实现类型”。

## 已移除的重复 owner

- `semantic-language` 不再保存 universal payload dataclass；本包只保留 role vocabulary、reference、canonicalization 和 non-substitution rule。
- `Responsibility` 只有一个 durable owner model，不再存在独立 `StandingResponsibility` payload。
- Decision currentness 属于 Decision owner lifecycle，不再使用平行 qualification object。
- Qualification 使用 `QualificationBinding + ReviewCase`；assessment 与 resolution 是同一个 review 上的 transition，不再各自制造顶层 durable object。
- Goal payload/lifecycle 属于 strategy。
- Mandate payload/lifecycle 属于 governance。
- Revision payload/lineage 属于 lineage。
- Claim/Evidence/Unknown payload 与 epistemic assessment model 属于 epistemics。

## 刻意不合并

实现形态相似的对象，只要回答的问题或携带的 authority 不同，就继续分离。
Epistemic assessment、Responsibility assessment、strategy assessment、authorization use
和 review resolution 不能互相替代。

即使 payload owner 是本地的，以下 hard semantic boundary 仍必须保留：

- Claim != Evidence
- Decision != Authorization
- Authorization != Effect
- Effect != Outcome
- Responsibility != Effect

## 扩展规则

新的 domain concept 应扩展自己的 owner module；需要跨 subsystem 引用时使用
non-universal namespace。增加一个 domain feature 不应要求增加 universal dataclass
或修改中央 payload registry。
