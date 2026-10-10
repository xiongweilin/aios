# P7 Internal Read-Only Maintenance Pilot — Implementation and Readiness Report

- Date: 2026-10-08
- State: Candidate-1 Odoo staging preflight qualified four times; all four observer starts stopped before sampling because `ON-DUTY` did not reach the TTY within its gate. The pilot remains **0/960** and is incomplete; no promotion or operational acceptance is supported.
- Frozen contract: `p7_internal_readonly_pilot_v1.json`, unchanged (`design_frozen_not_authorized`).

## 中文

### 结论

独立的四小时 GET-only observer、预检门、值守停止/升级、成本记录、断点证据、只读 loopback relay，以及离线故障测试已实现。stock Odoo 根路径预检曾因重定向未合格；候选一的空白 Odoo staging 四次预检均合格。但四次 `observe` 均因 `ON-DUTY` 未及时到达 TTY 而停止，PilotRunner 未启动；四小时观测仍 **0/960**，不是服务错误率或运营验收结论。

五轮实际预检共发送 **20 次 GET**（每源每轮一次）：stock Odoo 栈因 `/` 重定向未合格；候选一 Odoo 栈四轮四源均 `ok`。另有两次启动尝试在预检探测前失败，没有发出 GET。四次 `observe` 均未在 60 秒确认窗口内收到 TTY 输入，故 **0/960** 观测槽位。未调用模型、未访问真实员工数据、未执行员工/业务写入。

### 当前 readiness 证据

- 主 Compose 项目 `aios` 未被本次操作修改。八个独立项目包括先前五次准备/预检，以及本次 r5（预检前停止）、r6（预检目录冲突）和 r7（预检合格、值守门超时）。所有项目容器/网络均已停止/移除；16 个 Odoo/runtime 合成 volume 保留（未用 `down -v`），当前无 P7 容器运行。
- 本地栈来自 `tests/acceptance/baa_offboarding/real_e2e/compose.yaml`，另用独立 `p7-local-compose.yaml` overlay 和空 Keycloak realm（`users=[]`、`clients=[]`）；Keycloak 导入依据其官方 `--import-realm` 启动机制，[官方说明](https://www.keycloak.org/server/importExport)。端口仅绑定 `127.0.0.1`；Runtime 周期 healthcheck 关闭且直出端口移除，避免代理之外访问和未计数 Runtime 读请求。预检数据文件与 SHA-256 sidecar 在仓库外受限目录，checksum 已核验。
- 候选一的 P7 专用 addon `p7_root_health` 已安装在四个全新空白 Odoo staging 数据库中；其 `GET /` 只返回静态 200，`auth=none`、`save_session=False`、`readonly=True`，不访问 ORM/session。四轮四源预检均验证该路由返回 `ok`。这改变的是合成 staging 根路由，不改变冻结契约，也不代表 stock Odoo 根路径行为。
- AIOS 仓库根 `.env` 与 BAA 子目录 `.env` 均不存在；`.env.example` 只是模板。Windows Credential Manager 未发现 BAA/P7/Keycloak/Odoo 对应目标，进程中也没有 `BAA_REAL_*` / `BAA_P7_*` 值。`commerce-orchestrator` 另有 `dev` Odoo 配置与 API key，但属于不同项目，未读取或转用其 secret。
- 现有 `real_e2e/run.py` 会创建合成员工并调用写接口，本任务明确未执行它。局部栈只用于 empty-realm、无 demo employee 的准备；P7 sampler 通过独立 GET-only relay 访问 Runtime，使用短时 bearer token 和 loopback 端点。
- 候选一前四次合格预检（含本次 r7）的四源结果均为 `status=qualified`、4/4 `ok`，sidecar 校验通过。r6 因预先创建了 sampler 要以 `exist_ok=False` 独占创建的 `preflight` 目录，在探测循环前失败；r5 同样没有留下预检证据，具体异常未持久化。r7 的 `observe` 在 60 秒值守门后以退出码 2 结束；TTY 没有任何操作事件，partial journal 为 0 observations / 0 operator events，无 manifest/SHA256SUMS。该门要求新鲜的终端输入以证明值守人员在场；授权或聊天中的旧信号不替代该证据。
- 证据 lineage：候选一 run 1（revision `eec3caab996e9cfd97ad4c0b44095d813111c395`）：activation SHA-256 `e5a64ba9a91eaa28acaeaf58adf486bb7857f03426c4c945e42a1919123c2243`，preflight `1512b1235e3b4d363a362af668d5800d1c5298258b1c28bd955a1214d1d7abda`，gate `9c427d19284a601a678c09133c9f982b0d4e6664cb06a1d3b5fd5d3b1622add3`。Run 2（revision `b30c0d1999a17a98d10594ac76ef1689a9e8c756`）：activation `4ad80acd7c45cd072f2db060af6e32869f127c3ffd0021a5fbfcfb3757a1dc20`，preflight `77a03215d1936f80acb165f0cf966201b010a470f35c6463e8b5c1de0a293c6e`，gate `c69db8dc1a756d62c826bbf75c40d011e34a0e2002ed964d518f1c267c1e087d`。Run 3（revision `4fed5c68c3a1122f63bb284a809fdfb9d71c2c4f`）：activation `9c5dccd8c90f44b520075da885ac163e78c48e40f279141f54430469cf68c37b`，preflight `ea20808404b2215075ac663ee9a4f1fe554cbb78d1ca3879ab1a6a0bb0a79aba`，gate `159b8ac48f1fc7730d614dc3232c2913a1a92903ea6b9b29f2ae0c8fcfc1abbd`。三个 run 的 instrument SHA-256 均为 `6d55adeb3a76e19b280c9fdba1c6011a532f6a7c4e8da9ba5222f80d61354ff7`，冻结契约 SHA-256 均为 `0d17bcc59f93ec2e2a7eacb3f39a8b4193f5349dea195350d06a99ca1bd9050c`；所有 sidecar 匹配。Stock Odoo 失败证据另行保留。

- 本次新证据均在仓库外受限目录。r5（revision `b5490bf344c602e746de4502c0d6cccd7bc603a3`）activation SHA-256 `761226167ec3a280feba31fed778626a71ffa4d9972281e3a912097a036c3536`，无 preflight/gate 文件。r6 同 revision，activation `a119555c9e5ad4c2ed606c6cf4406770d34b864ef537f456f6ed0f0864420ca1`，因上述独占目录冲突无 preflight/gate 文件。r7 activation `6a65425fe385c7b4d48eaca3b80ba0ccb07cde8b82c34a67117ffc5b8b84714b`，qualified preflight `41c92b499f5fcd676e2fbe898bd4a477aee8d61d73e27e1d21982580e2be72c3`，gate `3b25ea71c684f8e76c359a5829cab54ea141e6e852d0519d4997db0b951fe193`；gate 记录 observer 退出码 2 和 UTC 窗口 `2026-10-08T09:56:22Z`–`09:57:22Z`。本次 instrument SHA-256 仍为 `6d55adeb3a76e19b280c9fdba1c6011a532f6a7c4e8da9ba5222f80d61354ff7`，冻结契约 SHA-256 仍为 `0d17bcc59f93ec2e2a7eacb3f39a8b4193f5349dea195350d06a99ca1bd9050c`；新激活、合格预检和 gate sidecar 均匹配。

本次已打开独立可见 PowerShell 窗口并明确标出 `RETRY r7`，但 60 秒值守门仍未收到终端输入。四次 observer 启动均未通过冻结值守门；“0/960”表示未采样，而非零错误率或服务健康结论。候选仍为未完成评估状态，不晋级。

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

候选一四轮四源预检均通过；四次值守门都超时，没有采样。第三次用户在 TTY 提示前发送了 `ON-DUTY`，但未在 60 秒窗口内转入 TTY，不能追溯算作确认。当前没有有效的值守确认；下一次 activation 需要在新提示出现时收到一条新鲜的人工 `ON-DUTY`，之后仅逐字转发用户实际输入的 `ACK`/`STOP` 等命令，不自动生成。

## English

### Outcome

The independent four-hour GET-only observer, preflight gate, operator stop/escalation, cost accounting, resumable evidence checkpoints, read-only loopback relay, and offline fault tests are implemented. The stock-Odoo preflight was unqualified due to a root redirect; all four candidate-1 preflights qualified, but all four observer starts stopped at the human `ON-DUTY` gate. The latest attempt used a separate visible PowerShell window; no terminal input arrived during the 60-second gate. The pilot remains incomplete, not a service error-rate finding or operational acceptance.

Five actual preflight rounds made **20 GET requests** (four per round): the stock Odoo root redirected in the first round; all four candidate-1 rounds returned `ok` for all four sources. Two additional launch attempts stopped before any probe. Four `observe` commands failed the 60-second `ON-DUTY` gate, so `PilotRunner` never started and the four-hour window remains **0/960**. No model was called, no real employee data was accessed, and no business write was performed.

### Readiness evidence

- The main local Compose project `aios` was not changed by these attempts. Eight isolated P7 projects are stopped: the earlier five plus r5 (preflight not reached), r6 (preflight output-directory collision), and r7 (qualified preflight, then no timely TTY confirmation). All 16 synthetic Odoo/runtime volumes were retained (no `down -v`); no P7 containers now run.
- The synthetic source stack is `tests/acceptance/baa_offboarding/real_e2e/compose.yaml`, with a separate `p7-local-compose.yaml` overlay and empty Keycloak realm (`users=[]`, `clients=[]`), imported with Keycloak's documented `--import-realm` startup option ([official docs](https://www.keycloak.org/server/importExport)). Ports bind only to `127.0.0.1`; Runtime's periodic healthcheck and direct host port were disabled to prevent reads outside the meter. Preflight JSON and SHA-256 sidecar are stored outside the repository in a restricted directory; the checksum was verified.
- Candidate 1's P7-only addon `p7_root_health` was installed in four fresh empty Odoo staging databases. It subclasses Odoo 18 `Home.index`, serves only `GET /`, uses `auth=none`, `save_session=False`, and `readonly=True`, returns a static 200, and accesses no ORM/session. All four candidate-1 preflights verified the route as `ok`. This follows Odoo's documented controller-extension mechanism ([Odoo 18 docs](https://www.odoo.com/documentation/18.0/developer/reference/backend/http.html)); official Odoo 18 source shows the stock root redirects to `/odoo` ([source](https://raw.githubusercontent.com/odoo/odoo/18.0/addons/web/controllers/home.py)). This changes only the synthetic staging root, not the frozen contract, and is not a claim about stock Odoo behavior.
- The repository-root `.env` and BAA-subdirectory `.env` are absent; `.env.example` is only a template. Windows Credential Manager has no BAA/P7/Keycloak/Odoo target, and no `BAA_REAL_*` / `BAA_P7_*` variables were present. A separate `commerce-orchestrator` `.env` describes a `dev` Odoo configuration and an API key, but belongs to another project; its secret was not read or reused.
- The existing `real_e2e/run.py` creates synthetic employee records and invokes write endpoints, so it was not run. The local overlay prepares only an empty-realm, no-demo-employee stack. The P7 sampler uses a separate GET-only Runtime relay, short-lived bearer credential, and loopback endpoints.
- The latest three activation records are sidecar-verified. r5 stopped before preflight and did not retain its exception; r6 failed because its already-created preflight directory conflicts with the sampler's `mkdir(exist_ok=False)`, before the probe loop; r7 left that directory absent, qualified all four sources, then exited code 2 after the 60-second gate with no operator input. The r7 partial journal has 0 observations and 0 operator events and no manifest or `SHA256SUMS`; its supplemental gate record and checksum are retained.
- Candidate 1 run 1 (revision `eec3caab996e9cfd97ad4c0b44095d813111c395`): activation `e5a64ba9a91eaa28acaeaf58adf486bb7857f03426c4c945e42a1919123c2243`; preflight `1512b1235e3b4d363a362af668d5800d1c5298258b1c28bd955a1214d1d7abda`; gate `9c427d19284a601a678c09133c9f982b0d4e6664cb06a1d3b5fd5d3b1622add3`. Run 2 (revision `b30c0d1999a17a98d10594ac76ef1689a9e8c756`): activation `4ad80acd7c45cd072f2db060af6e32869f127c3ffd0021a5fbfcfb3757a1dc20`; preflight `77a03215d1936f80acb165f0cf966201b010a470f35c6463e8b5c1de0a293c6e`; gate `c69db8dc1a756d62c826bbf75c40d011e34a0e2002ed964d518f1c267c1e087d`. Run 3 (revision `4fed5c68c3a1122f63bb284a809fdfb9d71c2c4f`): activation `9c5dccd8c90f44b520075da885ac163e78c48e40f279141f54430469cf68c37b`; preflight `ea20808404b2215075ac663ee9a4f1fe554cbb78d1ca3879ab1a6a0bb0a79aba`; gate `159b8ac48f1fc7730d614dc3232c2913a1a92903ea6b9b29f2ae0c8fcfc1abbd`. The instrument SHA-256 is `6d55adeb3a76e19b280c9fdba1c6011a532f6a7c4e8da9ba5222f80d61354ff7`; frozen-contract SHA-256 is `0d17bcc59f93ec2e2a7eacb3f39a8b4193f5349dea195350d06a99ca1bd9050c`. All listed sidecars match; the earlier stock-root unqualified evidence is preserved separately.

- New evidence (revision `b5490bf344c602e746de4502c0d6cccd7bc603a3`): r5 activation `761226167ec3a280feba31fed778626a71ffa4d9972281e3a912097a036c3536`, no preflight/gate artifact; r6 activation `a119555c9e5ad4c2ed606c6cf4406770d34b864ef537f456f6ed0f0864420ca1`, no preflight/gate artifact; r7 activation `6a65425fe385c7b4d48eaca3b80ba0ccb07cde8b82c34a67117ffc5b8b84714b`, qualified preflight `41c92b499f5fcd676e2fbe898bd4a477aee8d61d73e27e1d21982580e2be72c3`, and gate `3b25ea71c684f8e76c359a5829cab54ea141e6e852d0519d4997db0b951fe193`. r7 observer exit code was 2 after the UTC interval `2026-10-08T09:56:22Z`–`09:57:22Z`, with zero observations/events. The instrument and frozen-contract hashes above are unchanged; all r5/r6/r7 activation sidecars and r7 preflight/gate sidecars match.

The candidate remains unpromoted and unevaluated operationally. A fresh `ON-DUTY` must be entered by the named on-duty operator at the visible TTY prompt; authorization and an earlier chat message do not establish operator presence. Four observer starts stopped at that gate. “0/960” remains an unobserved pilot denominator, not a 0% error rate or healthy-service result.

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

All four candidate-1 preflights qualified, but all four observer starts timed out because no `ON-DUTY` reached the TTY in time. The third user-supplied token arrived before the TTY prompt and was not relayed within the 60-second window; it does not count. A future activation requires a fresh human `ON-DUTY` at its prompt. The wrapper will stream TTY output and use the approved private thread as the contact route; only exact user-entered `ON-DUTY`/`ACK` strings will be relayed, never generated automatically. If no timely input arrives, stop without sampling.
