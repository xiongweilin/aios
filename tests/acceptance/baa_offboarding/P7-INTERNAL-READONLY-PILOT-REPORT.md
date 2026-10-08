# P7 Internal Read-Only Maintenance Pilot — Implementation and Readiness Report

- Date: 2026-10-08
- State: Instrument and isolated local-stack overlay implemented and offline-qualified; live preflight not yet started.
- Frozen contract: `p7_internal_readonly_pilot_v1.json`, unchanged (`design_frozen_not_authorized`).

## 中文

### 结论

独立的四小时 GET-only observer、预检门、值守停止/升级、成本记录、断点证据、只读 loopback relay，以及离线故障测试已实现。当前尚未启动预检，真实试点仍为**未启动（NOT QUALIFIED）**，不是服务健康/故障结论，也不是运营验收通过。

本次没有向 staging 发 HTTP 请求：预检 **0 次**；四小时窗口 **0/960 个已观察槽位**。未调用模型，未访问真实员工数据，未执行业务写入。

### 当前 readiness 证据

- 本机 Compose 项目 `aios` 仍只有 8 个 AIOS 组件在运行；该主项目没有 Keycloak/Odoo staging。`tests/acceptance/baa_offboarding/real_e2e/compose.yaml` 另有 Odoo 18 / Keycloak 26.8 / Runtime 合成验收栈，本次新增独立 `p7-local-compose.yaml` overlay 和一个空 Keycloak realm（`users=[]`、`clients=[]`）。overlay 将端口限于 `127.0.0.1`、关闭 Runtime 周期 healthcheck、移除 Runtime 直出端口，避免代理之外的访问和未计数 Runtime 读请求。首次隔离栈已启动后停止；观察器入口路径拼接错误导致 Python 未启动，未发出 P7 请求。新项目重试尚未启动。
- AIOS 仓库根 `.env` 与 BAA 子目录 `.env` 均不存在；`.env.example` 只是模板。Windows Credential Manager 未发现 BAA/P7/Keycloak/Odoo 对应目标，进程中也没有 `BAA_REAL_*` / `BAA_P7_*` 值。`commerce-orchestrator` 另有 `dev` Odoo 配置与 API key，但属于不同项目，未读取或转用其 secret。
- 现有 `real_e2e/run.py` 会创建合成员工并调用写接口，本任务明确未执行它。局部栈只用于 empty-realm、无 demo employee 的准备；P7 sampler 通过独立 GET-only relay 访问 Runtime，使用短时 bearer token 和 loopback 端点。
- 首次尝试创建了仓库外 activation 文件，但观察器入口将相对路径重复拼接，Python 返回文件不存在；因此预检程序未执行，P7 HTTP 请求 **0 次**，观测 **0/960 槽位**。脚本停止并移除了该唯一 Compose 项目的容器/网络，未使用 `down -v`；仅保留该次初始化的两个合成数据卷和 activation 文件以供核查。将使用新项目名和新 activation 重试。冻结 readiness gate 是否通过仍须由真实短时预检决定。

用户随后明确批准在计划范围内继续，并指定由我查找本地授权/配置来源。本报告更新时正在准备独立 loopback staging；仍须先生成仓库外的逐项 activation 记录、跑短时预检并核验其资格，未通过就不得开始四小时观测。此前的“0 次请求”只描述本报告更新前的状态，不是健康结果。

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

- 定向 unittest：**13/13 通过**。包括模拟完整 240 轮/960 槽位、unknown 后两轮重新获取、超过 300 秒未恢复即停止、能力指纹漂移立即停止、人工 STOP、值守失联、成本超限、授权路径/loopback 与 HTTPS 检查、只读代理 GET/路径/token/delegation/expiry gate、空 realm 与 loopback Compose 边界、预检证据 hash 绑定、槽位/事件 hash chain 与 checkpoint 对账、错误详情脱敏，以及原 900 秒限制保持不变。
- Docker Compose overlay 静态合并检查通过：Runtime 无主机发布端口且禁用周期 healthcheck；Keycloak realm import 开启；只读代理仅绑定 loopback。检查使用 config-only dummy values，不启动服务、不创建容器。
- 冻结契约静态检查通过；直接运行 observer 的 `--help` 入口通过。
- 上述完整窗口测试使用模拟时钟和本地伪响应，**不是**四小时真实 staging 运行，也不证明远端服务可用或授权有效。
- 预注册 JSON 和阈值未修改；任何 live acceptance 仍须以外部授权、真实观测证据和独立审核为准。

### 真实执行前必须具备

启动前会将用户批准、本机账户 `metra`、四源 loopback 清单、GET-only relay 范围、独立 Compose stop/短时凭据过期路径，以及本机受限证据目录绑定到仓库外 activation record。随后只运行一次短时 `preflight`；只有资格通过，才由交互终端人工输入 `ON-DUTY` 启动四小时观测。任何前提无法验证或预检失败，都保留证据并停止，不扩大权限。

## English

### Outcome

The independent four-hour GET-only observer, preflight gate, operator stop/escalation, cost accounting, resumable evidence checkpoints, and offline fault tests are implemented. The current outcome is **pilot not started (NOT QUALIFIED)**—not a staging health/failure finding and not operational acceptance.

No staging HTTP requests were made: **0** preflight requests and **0/960** observed slots in the four-hour window. No model was called, no real employee data was accessed, and no business write was performed.

### Readiness evidence

- The local Compose project `aios` reports `running(8)`. Running containers are AIOS Runtime, Personal World, Control Plane, Administrative, Autonomous Development, Prometheus, and PostgreSQL components. No Keycloak or Odoo staging container is present.
- The main local Compose project `aios` still runs only its eight AIOS components and has no Keycloak/Odoo staging. A separate synthetic acceptance stack exists at `tests/acceptance/baa_offboarding/real_e2e/compose.yaml`; this change adds `p7-local-compose.yaml` and an empty Keycloak realm (`users=[]`, `clients=[]`). The overlay binds services to `127.0.0.1`, disables periodic Runtime healthchecks, and removes direct Runtime port publication, preventing out-of-band Runtime reads through the pilot window. One isolated project was started and then stopped; the observer path was accidentally duplicated, so Python never launched and no P7 request was sent. A new project retry has not started.
- The repository-root `.env` and BAA-subdirectory `.env` are absent; `.env.example` is only a template. Windows Credential Manager has no BAA/P7/Keycloak/Odoo target, and no `BAA_REAL_*` / `BAA_P7_*` variables were present. A separate `commerce-orchestrator` `.env` describes a `dev` Odoo configuration and an API key, but belongs to another project; its secret was not read or reused.
- The existing `real_e2e/run.py` creates synthetic employee records and invokes write endpoints, so it was not run. The local overlay prepares only an empty-realm, no-demo-employee stack. The P7 sampler uses a separate GET-only Runtime relay, short-lived bearer credential, and loopback endpoints.
- An external activation file was created for the first attempt, but a duplicated relative path caused Python to exit with “file not found” before preflight. Thus preflight-program runs **0**, P7 HTTP requests **0**, and observed slots **0/960**. The unique project's containers/network were removed without `down -v`; two synthetic volumes and that activation file remain for audit. The retry uses a new project name and activation. Only a real short preflight can establish whether the readiness gate passes.

The user subsequently authorized continuing within plan scope and directed a search of local authorization/configuration sources. This report revision is preparing a separate loopback staging fixture; it still requires an external, itemized activation record and a qualifying short preflight before any four-hour observation. Failure of that gate means no observation. The “0 requests” count describes state before this report update, not a healthy-service result.

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

- Focused unittest suite: **13/13 passed**. Coverage includes a simulated 240-round/960-slot window, unknown followed by two-round reacquisition, stopping after the 300-second reacquisition budget expires, immediate stop on capability drift, manual STOP, operator loss, cost overrun, activation path/loopback/HTTPS checks, read-only proxy method/path/token/delegation/expiry checks, empty realm and loopback Compose boundary, hash-bound preflight evidence, slot/event hash chains and checkpoint reconciliation, error-detail redaction, and preservation of the legacy 900-second limit.
- Docker Compose overlay merge validation passed: Runtime has no host-published port and no periodic healthcheck; Keycloak realm import is enabled; the read-only proxy binds only to loopback. This used config-only dummy values and did not start services or create containers.
- The frozen-contract static checker passed; the observer's direct `--help` entry point passed.
- The full-window test used a simulated clock and local fake responses. It is **not** a four-hour staging run and does not prove remote service availability or authorization.
- The preregistered JSON and thresholds were not changed. Any live acceptance decision still requires external authorization, real observations, and independent review.

### Required before real execution

Before launch, the private activation record will bind the user's approval, local account `metra`, exact four-source loopback inventory, GET-only relay scope, independent Compose stop/short-lived credential expiry, and a restricted local evidence directory. Run only the short `preflight`; start the four-hour observer only if its qualification result is positive and a human enters `ON-DUTY` in the interactive terminal. If any prerequisite is unverified or fails, retain evidence and stop without widening privileges.
