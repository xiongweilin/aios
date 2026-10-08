# P7 Internal Read-Only Maintenance Pilot — Implementation and Readiness Report

- Date: 2026-10-08
- State: Candidate-1 Odoo staging preflight qualified; supervised observer start was not confirmed; pilot remains **0/960** and not complete.
- Frozen contract: `p7_internal_readonly_pilot_v1.json`, unchanged (`design_frozen_not_authorized`).

## 中文

### 结论

独立的四小时 GET-only observer、预检门、值守停止/升级、成本记录、断点证据、只读 loopback relay，以及离线故障测试已实现。stock Odoo 根路径预检曾因重定向未合格；候选一的空白 Odoo staging 已有一轮合格预检。但 `observe` 在值守门因未收到 `ON-DUTY` 而停止，PilotRunner 未启动；四小时观测仍 **0/960**。这不是服务错误率或运营验收结论。

两轮真实预检共发送 **8 次 GET**（每源每轮一次）：stock Odoo 栈的首轮因 `/` 重定向未合格；候选一 Odoo 栈的第二轮四源均 `ok`。候选一的 `observe` 命令随后在值守确认期限内未收到人工输入，故 **0/960** 观测槽位。未调用模型、未访问真实员工数据、未执行员工/业务写入。

### 当前 readiness 证据

- 主 Compose 项目 `aios` 保持 8 个 AIOS 组件运行，未修改。三次独立项目依次为：observer 路径错误（0 请求）、stock Odoo 根路径预检重定向、候选一根路由预检通过但值守确认缺失。每个项目容器/网络均已停止/移除；三个项目各留 Odoo/runtime 合成 volume（未用 `down -v`），目前无 P7 容器、端口空闲，镜像已缓存。
- 本地栈来自 `tests/acceptance/baa_offboarding/real_e2e/compose.yaml`，另用独立 `p7-local-compose.yaml` overlay 和空 Keycloak realm（`users=[]`、`clients=[]`）；Keycloak 导入依据其官方 `--import-realm` 启动机制，[官方说明](https://www.keycloak.org/server/importExport)。端口仅绑定 `127.0.0.1`；Runtime 周期 healthcheck 关闭且直出端口移除，避免代理之外访问和未计数 Runtime 读请求。预检数据文件与 SHA-256 sidecar 在仓库外受限目录，checksum 已核验。
- 候选一的 P7 专用 addon `p7_root_health` 已在第三个全新空白 Odoo staging 中安装；其 `GET /` 只返回静态 200，`auth=none`、`save_session=False`、`readonly=True`，不访问 ORM/session。四源预检已验证该路由返回 `ok`。这改变的是合成 staging 根路由，不改变冻结契约，也不代表 stock Odoo 根路径行为。
- AIOS 仓库根 `.env` 与 BAA 子目录 `.env` 均不存在；`.env.example` 只是模板。Windows Credential Manager 未发现 BAA/P7/Keycloak/Odoo 对应目标，进程中也没有 `BAA_REAL_*` / `BAA_P7_*` 值。`commerce-orchestrator` 另有 `dev` Odoo 配置与 API key，但属于不同项目，未读取或转用其 secret。
- 现有 `real_e2e/run.py` 会创建合成员工并调用写接口，本任务明确未执行它。局部栈只用于 empty-realm、无 demo employee 的准备；P7 sampler 通过独立 GET-only relay 访问 Runtime，使用短时 bearer token 和 loopback 端点。
- 候选一 activation 的四源预检 `status=qualified`、4/4 `ok`，sidecar 校验通过。随后 `observe` 命令打印 TTY 提示，但 60 秒内没有收到 `ON-DUTY`，以 `on_duty_operator_confirmation_missing` 退出；用户确认未看到提示。原因已查明：wrapper 捕获了 observer 输出而未实时显示，Codex terminal attach 也保持 `queued`。因此 PilotRunner 未启动，partial journal 为 0 observations / 0 operator events，无 manifest/SHA256SUMS。仓库外补充 gate 记录保留此退出结果。
- 证据 lineage：候选一来源提交 `eec3caab996e9cfd97ad4c0b44095d813111c395`；instrument SHA-256 `6d55adeb3a76e19b280c9fdba1c6011a532f6a7c4e8da9ba5222f80d61354ff7`，冻结契约 SHA-256 `0d17bcc59f93ec2e2a7eacb3f39a8b4193f5349dea195350d06a99ca1bd9050c`。候选一 activation SHA-256 `e5a64ba9a91eaa28acaeaf58adf486bb7857f03426c4c945e42a1919123c2243`；合格 preflight JSON SHA-256 `1512b1235e3b4d363a362af668d5800d1c5298258b1c28bd955a1214d1d7abda`；补充 operator gate 记录 SHA-256 `9c427d19284a601a678c09133c9f982b0d4e6664cb06a1d3b5fd5d3b1622add3`。各自 sidecar 均校验相符。此前 stock Odoo 预检失败记录也保留；没有任何 observe manifest。

用户已确认此前看不到终端提示并要求继续。当前仍没有人工 `ON-DUTY`，所以冻结值守门阻止 PilotRunner；“0/960”表示未采样，不是服务健康结论。

### 实现范围

- 新增独立入口 `real_e2e/p7_internal_readonly_pilot.py`：四源固定顺序、仅 `GET`、每槽位最多一次、单请求 3 秒超时；Runtime capability 指纹缺失、弱化或漂移时 fail-closed，漂移在下一源请求前立即停止。未配置重定向跟随，也不保存响应体、完整 URL、凭据或员工数据。
- 运行窗口绑定外部 activation record 中的固定 UTC 起止，并以单调时钟计时；每 60 秒一轮、240 轮、960 个槽位。所有提前停止或未尝试槽位仍写入分母。原 `p7_shadow_readonly.py` 的 900 秒 / 300 轮限制未改。
- Activation 必须在仓库外提供完整授权/责任/清单/只读范围/停止撤权/证据保留引用和逐项 attestations。准确路径及 realm 被校验；远端 bearer 源必须为 HTTPS；此隔离测试栈仅接受绑定 `127.0.0.1` / `localhost` 的 HTTP loopback 地址。Runtime 的 P7 token 只由 loopback relay 接受，relay 仅放行 `GET /healthz` 和 `GET /v1/capabilities`，使用固定上游路径、独立 delegation 校验和 pilot-end 过期时间；上游 controller token 不注入 observer 进程。Keycloak/Odoo 使用无凭据 GET。秘密值不写入仓库或报告。
- 观察期需交互式终端输入 `ON-DUTY`，并至少每 900 秒 `ACK`；支持 `STOP` 与 Ctrl+C。401/403、契约问题、未知分类、值守缺席、超预算或证据异常均停止并保留失败分类。网络 unknown 只有在之后两轮全源干净观测后才记为证据重新获取，不抹除先前 unknown。
- `ATTENTION START/STOP` 与 `ASSURANCE START/STOP` 分别记录 principal attention 和第三方 assurance labor；自动监控时长与外部只读次数单独计数。成本超冻结预算即停止。
- 观测槽位与操作事件使用独立 hash chain；checkpoint 对两条链的记录数和末端 hash 对账。正常结束输出 manifest、资格结果及 `SHA256SUMS`。证据目录必须位于仓库外；14 天访问/保留控制由运营方落实并由独立审核人核查，脚本不会伪称自行执行该治理。

私有 activation record 的 schema 标识为 `aios-p7-internal-readonly-pilot-activation-v1`。真实 activation 文件、staging URLs、realm、身份和 secret 不进入仓库或本报告。

私有记录必须包含 `references`（approval、accountable owner、on-duty operator、private contact route、written read authorization、credential-scope attestation、resource inventory、independent stop、credential revocation、evidence access/retention）；`attestations` 中对应的十项布尔证明；恰好四个 `resources`（`runtime_health`、`runtime_capabilities`、`keycloak_realm`、`odoo_root`）；`auth_modes`、`runtime_delegation_id`、`approved_realm`，以及独立的 `preflight_window` 和严格四小时 `pilot_window`。这些只是外部授权记录的字段要求，不构成授权本身。

授权与证据准备齐备后，人工入口为：

```powershell
python tests/acceptance/baa_offboarding/real_e2e/p7_internal_readonly_pilot.py preflight --activation-file <仓库外的私有授权文件> --evidence-dir <仓库外的受限新目录>
python tests/acceptance/baa_offboarding/real_e2e/p7_internal_readonly_pilot.py observe --activation-file <同一私有授权文件> --evidence-dir <仓库外的受限新目录> --preflight-proof <合格的 preflight.json>
```

第一条必须在批准的短时预检窗口内执行；第二条要求交互式终端，并且只在预检合格、observer 代码/契约/资源清单 hash 一致时启动。

### 验证结果

- 定向 unittest：**13/13 通过**。包括模拟完整 240 轮/960 槽位、unknown 后两轮重新获取、超过 300 秒未恢复即停止、能力指纹漂移立即停止、人工 STOP、值守失联、成本超限、授权路径/loopback 与 HTTPS 检查、只读代理 GET/路径/token/delegation/expiry gate、Odoo 根控制器仅 GET/无 session/ORM 的静态约束、空 realm 与 loopback Compose 边界、预检证据 hash 绑定、槽位/事件 hash chain 与 checkpoint 对账、错误详情脱敏，以及原 900 秒限制保持不变。
- Docker Compose overlay 静态合并检查通过：Runtime 无主机发布端口且禁用周期 healthcheck；Keycloak realm import 开启；只读代理仅绑定 loopback。检查使用 config-only dummy values，不启动服务、不创建容器。
- 冻结契约静态检查通过；直接运行 observer 的 `--help` 入口通过。
- 上述完整窗口测试使用模拟时钟和本地伪响应，**不是**四小时真实 staging 运行，也不证明远端服务可用或授权有效。
- 预注册 JSON 和阈值未修改；任何 live acceptance 仍须以外部授权、真实观测证据和独立审核为准。

### 结果与后续门槛

候选一四源预检已通过；但值守确认门未收到 `ON-DUTY`，因此未开始采样。下一次 wrapper 将实时转发 TTY 输出；本 thread 作为 activation 已登记的私密联系路线。提示时仅在用户亲自发送精确 `ON-DUTY`/`ACK` 后，我才逐字转发该字符串到 TTY；不会自动生成确认，超时仍按规则停止。

## English

### Outcome

The independent four-hour GET-only observer, preflight gate, operator stop/escalation, cost accounting, resumable evidence checkpoints, read-only loopback relay, and offline fault tests are implemented. The stock-Odoo preflight was unqualified due to a root redirect; candidate 1's isolated Odoo preflight qualified, but the observer stopped before sampling because its human `ON-DUTY` gate timed out. This is neither a service error-rate finding nor operational acceptance.

Two actual preflight rounds made **eight GET requests** (four per round): the stock Odoo root redirected in round one; all four sources were `ok` in candidate 1. The subsequent `observe` command received no `ON-DUTY` within its 60-second gate, so `PilotRunner` never started and the four-hour window remains **0/960**. No model was called, no real employee data was accessed, and no business write was performed.

### Readiness evidence

- The main local Compose project `aios` still reports `running(8)` and was not changed. Three isolated P7 projects were stopped and removed: a wrapper path error (0 requests), a stock Odoo redirect preflight, then candidate 1 (qualified preflight but missing operator confirmation). Each project's synthetic Odoo/runtime volumes were retained (no `down -v`); no P7 containers now run and ports are free. Odoo/Keycloak/Postgres images remain cached.
- The synthetic source stack is `tests/acceptance/baa_offboarding/real_e2e/compose.yaml`, with a separate `p7-local-compose.yaml` overlay and empty Keycloak realm (`users=[]`, `clients=[]`), imported with Keycloak's documented `--import-realm` startup option ([official docs](https://www.keycloak.org/server/importExport)). Ports bind only to `127.0.0.1`; Runtime's periodic healthcheck and direct host port were disabled to prevent reads outside the meter. Preflight JSON and SHA-256 sidecar are stored outside the repository in a restricted directory; the checksum was verified.
- Candidate 1's P7-only addon `p7_root_health` was installed in the third, empty Odoo staging database. It subclasses Odoo 18 `Home.index`, serves only `GET /`, uses `auth=none`, `save_session=False`, and `readonly=True`, returns a static 200, and accesses no ORM/session. The four-source preflight verified the route as `ok`. This follows Odoo's documented controller-extension mechanism ([Odoo 18 docs](https://www.odoo.com/documentation/18.0/developer/reference/backend/http.html)); official Odoo 18 source shows the stock root redirects to `/odoo` ([source](https://raw.githubusercontent.com/odoo/odoo/18.0/addons/web/controllers/home.py)). This changes only the synthetic staging root, not the frozen contract, and is not a claim about stock Odoo behavior.
- The repository-root `.env` and BAA-subdirectory `.env` are absent; `.env.example` is only a template. Windows Credential Manager has no BAA/P7/Keycloak/Odoo target, and no `BAA_REAL_*` / `BAA_P7_*` variables were present. A separate `commerce-orchestrator` `.env` describes a `dev` Odoo configuration and an API key, but belongs to another project; its secret was not read or reused.
- The existing `real_e2e/run.py` creates synthetic employee records and invokes write endpoints, so it was not run. The local overlay prepares only an empty-realm, no-demo-employee stack. The P7 sampler uses a separate GET-only Runtime relay, short-lived bearer credential, and loopback endpoints.
- Candidate 1's private activation and qualified preflight have valid SHA-256 sidecars. `observe` printed the TTY prompt but received no `ON-DUTY` within 60 seconds; the user confirmed the prompt was not visible. The wrapper had captured rather than streamed observer output, while the Codex terminal attachment remained queued. The partial journal contains 0 observations and 0 operator events; no manifest or `SHA256SUMS` was produced. A supplemental gate record preserves the exit result.
- Candidate 1 lineage: source revision `eec3caab996e9cfd97ad4c0b44095d813111c395`; instrument SHA-256 `6d55adeb3a76e19b280c9fdba1c6011a532f6a7c4e8da9ba5222f80d61354ff7`; frozen-contract SHA-256 `0d17bcc59f93ec2e2a7eacb3f39a8b4193f5349dea195350d06a99ca1bd9050c`; activation SHA-256 `e5a64ba9a91eaa28acaeaf58adf486bb7857f03426c4c945e42a1919123c2243`; qualified preflight SHA-256 `1512b1235e3b4d363a362af668d5800d1c5298258b1c28bd955a1214d1d7abda`; supplemental gate record SHA-256 `9c427d19284a601a678c09133c9f982b0d4e6664cb06a1d3b5fd5d3b1622add3`. Sidecars match. The earlier stock-root unqualified evidence remains separately preserved.

The user authorized candidate 1 and confirmed the earlier prompt was not visible. The candidate 1 preflight qualified, but the observer's human gate did not receive `ON-DUTY`, so the frozen control stopped before sampling. “0/960” is an unobserved pilot denominator, not a 0% error rate or healthy-service result.

### Implementation

- Added the separate entry point `real_e2e/p7_internal_readonly_pilot.py`: fixed four-source order, `GET` only, at most one attempt per slot, and a three-second request timeout. Missing/weakened/drifting Runtime capability contracts fail closed; drift stops before the next source request. Redirects are not followed. Response bodies, full URLs, credentials, and employee data are not persisted.
- The window is bound to fixed UTC start/end values in an external activation record and measured with a monotonic clock: one round every 60 seconds, 240 rounds, 960 slots. Early-stop and unattempted slots remain in the denominator. The existing `p7_shadow_readonly.py` limit of 900 seconds / 300 rounds is unchanged.
- Activation requires external references and attestations for authorization, accountability, inventory, read-only scope, stop/revocation, and evidence handling. Exact paths and realm are checked; remote bearer sources require HTTPS, while this isolated test stack permits HTTP only on `127.0.0.1` / `localhost`. The Runtime P7 token is accepted only by a loopback relay that allows `GET /healthz` and `GET /v1/capabilities`, validates the delegation, forwards fixed paths, and expires at pilot end. The upstream controller token is not passed to the observer process. Keycloak/Odoo use unauthenticated GETs. Secret values are not stored in the repository or report.
- An interactive operator must enter `ON-DUTY` and acknowledge at least every 900 seconds. `STOP` and Ctrl+C are supported. 401/403, contract discrepancies, uncategorized outcomes, operator absence, budget overruns, and evidence faults stop sampling and preserve classifications. A network unknown is only classified as evidence reacquired after two subsequent clean full-source rounds; the original unknown remains recorded.
- `ATTENTION START/STOP` and `ASSURANCE START/STOP` separately track principal attention and third-party assurance labor. Automated monitor runtime and external read count are separately reported. Exceeding a frozen cost budget stops sampling.
- Observation slots and operator events have separate hash chains; checkpoints reconcile both record counts and terminal hashes. Normal termination emits a manifest, qualification result, and `SHA256SUMS`. Evidence must be stored outside the repository. Operators enforce the 14-day access/retention controls and an independent reviewer checks them; the script does not claim to enforce that governance itself.

The private activation record schema identifier is `aios-p7-internal-readonly-pilot-activation-v1`. No real activation file, staging URL, realm, identity, or secret is included in the repository or this report.

The private record must contain `references` for approval, accountable owner, on-duty operator, private contact route, written read authorization, credential-scope attestation, resource inventory, independent stop, credential revocation, and evidence access/retention; all ten corresponding Boolean attestations; exactly four `resources` (`runtime_health`, `runtime_capabilities`, `keycloak_realm`, `odoo_root`); `auth_modes`, `runtime_delegation_id`, `approved_realm`, and separate `preflight_window` and exact four-hour `pilot_window` values. These are required fields for an external authorization record, not authorization by themselves.

After authorization and evidence storage are ready, the manual entry points are:

```powershell
python tests/acceptance/baa_offboarding/real_e2e/p7_internal_readonly_pilot.py preflight --activation-file <private-authorization-file-outside-the-repository> --evidence-dir <new-restricted-directory-outside-the-repository>
python tests/acceptance/baa_offboarding/real_e2e/p7_internal_readonly_pilot.py observe --activation-file <same-private-authorization-file> --evidence-dir <new-restricted-directory-outside-the-repository> --preflight-proof <qualified-preflight.json>
```

The first command must run within the approved short preflight window. The second requires an interactive terminal and starts only when preflight qualifies and observer/code/contract/resource-inventory hashes match.

### Verification

- Focused unittest suite: **13/13 passed**. Coverage includes a simulated 240-round/960-slot window, unknown followed by two-round reacquisition, stopping after the 300-second reacquisition budget expires, immediate stop on capability drift, manual STOP, operator loss, cost overrun, activation path/loopback/HTTPS checks, read-only proxy method/path/token/delegation/expiry checks, static Odoo root controller constraints (GET-only, no session/ORM), empty realm and loopback Compose boundary, hash-bound preflight evidence, slot/event hash chains and checkpoint reconciliation, error-detail redaction, and preservation of the legacy 900-second limit.
- Docker Compose overlay merge validation passed: Runtime has no host-published port and no periodic healthcheck; Keycloak realm import is enabled; the read-only proxy binds only to loopback. This used config-only dummy values and did not start services or create containers.
- The frozen-contract static checker passed; the observer's direct `--help` entry point passed.
- The full-window test used a simulated clock and local fake responses. It is **not** a four-hour staging run and does not prove remote service availability or authorization.
- The preregistered JSON and thresholds were not changed. Any live acceptance decision still requires external authorization, real observations, and independent review.

### Outcome and next gate

Candidate 1's preflight qualified, but its observer start timed out because no human `ON-DUTY` reached the TTY. The Codex terminal attachment remained queued and the wrapper buffered its output. The next wrapper will stream TTY output; the approved private thread will be the activation's contact route. Only exact human-entered `ON-DUTY`/`ACK` strings will be relayed to the TTY; no automatic confirmations will be sent. If no human input arrives by the deadline, stop again without sampling.
