# P7 Internal Read-Only Maintenance Pilot — Implementation and Readiness Report

- Date: 2026-10-08
- State: Instrument implemented and offline-qualified; live staging pilot not started.
- Frozen contract: `p7_internal_readonly_pilot_v1.json`, unchanged (`design_frozen_not_authorized`).

## 中文

### 结论

独立的四小时 GET-only observer、预检门、值守停止/升级、成本记录、断点证据与离线故障测试已实现。当前结果是**未启动试点（NOT QUALIFIED）**，不是 staging 健康/故障结论，也不是运营验收通过。

本次没有向 staging 发 HTTP 请求：预检 **0 次**；四小时窗口 **0/960 个已观察槽位**。未调用模型，未访问真实员工数据，未执行业务写入。

### 当前 readiness 证据

- 本机 Compose 项目 `aios` 显示 `running(8)`；当前运行容器是 AIOS Runtime、Personal World、Control Plane、Administrative、Autonomous Development、Prometheus 与 PostgreSQL 等组件。没有 Keycloak 或 Odoo staging 容器。
- 仓库没有 `.env`，只有 `.env.example` 模板；当前进程也没有 `BAA_P7_*` 凭据变量。模板值未作为授权或凭据使用。
- `docker compose config --services` 在当前进程环境下无法解析，因为 Compose 所需变量未提供；没有为此创建 `.env`、启动或修改容器。
- 本次没有提供可验证的四源 staging 清单、限时只读授权、只读身份/凭据范围证明、全窗口值守人及私密联络渠道、独立停止与试点凭据撤销途径、或受限证据存储批准。因此不满足冻结契约的 readiness gate。

上述缺项意味着不得运行真实预检或四小时观测。也没有把“没有请求”转写成 0% 错误率或服务健康结果。

### 实现范围

- 新增独立入口 `real_e2e/p7_internal_readonly_pilot.py`：四源固定顺序、仅 `GET`、每槽位最多一次、单请求 3 秒超时；Runtime capability 指纹缺失、弱化或漂移时 fail-closed，漂移在下一源请求前立即停止。未配置重定向跟随，也不保存响应体、完整 URL、凭据或员工数据。
- 运行窗口绑定外部 activation record 中的固定 UTC 起止，并以单调时钟计时；每 60 秒一轮、240 轮、960 个槽位。所有提前停止或未尝试槽位仍写入分母。原 `p7_shadow_readonly.py` 的 900 秒 / 300 轮限制未改。
- Activation 必须在仓库外提供完整授权/责任/清单/只读范围/停止撤权/证据保留引用和逐项 attestations。准确路径及 realm 被校验；凡使用 bearer 凭据的资源必须为 HTTPS。脚本只从 `BAA_P7_RUNTIME_TOKEN`、`BAA_P7_KEYCLOAK_BEARER_TOKEN`、`BAA_P7_ODOO_BEARER_TOKEN` 环境变量读取需要的凭据，不打印其值。当前没有这些变量。
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

- 定向 unittest：**11/11 通过**。包括模拟完整 240 轮/960 槽位、unknown 后两轮重新获取、超过 300 秒未恢复即停止、能力指纹漂移立即停止、人工 STOP、值守失联、成本超限、授权路径与 HTTPS 检查、预检证据 hash 绑定、槽位/事件 hash chain 与 checkpoint 对账、错误详情脱敏、以及原 900 秒限制保持不变。
- 冻结契约静态检查通过；直接运行 observer 的 `--help` 入口通过。
- 上述完整窗口测试使用模拟时钟和本地伪响应，**不是**四小时真实 staging 运行，也不证明远端服务可用或授权有效。
- 预注册 JSON 和阈值未修改；任何 live acceptance 仍须以外部授权、真实观测证据和独立审核为准。

### 真实执行前必须具备

运营方需先准备有效的私有 activation record、已批准四源准确清单、只读 HTTPS 凭据与隔离存储，确认 named owner/operator、全窗口覆盖、私密联络、独立 stop/revoke 路径和证据访问/14 天保留批准。随后在批准的短时窗口运行 `preflight`；只有预检资格通过，才可在同一代码与清单绑定下人工运行 `observe`。任何前提无法验证时继续停止，不扩大权限。

## English

### Outcome

The independent four-hour GET-only observer, preflight gate, operator stop/escalation, cost accounting, resumable evidence checkpoints, and offline fault tests are implemented. The current outcome is **pilot not started (NOT QUALIFIED)**—not a staging health/failure finding and not operational acceptance.

No staging HTTP requests were made: **0** preflight requests and **0/960** observed slots in the four-hour window. No model was called, no real employee data was accessed, and no business write was performed.

### Readiness evidence

- The local Compose project `aios` reports `running(8)`. Running containers are AIOS Runtime, Personal World, Control Plane, Administrative, Autonomous Development, Prometheus, and PostgreSQL components. No Keycloak or Odoo staging container is present.
- There is no repository `.env`; only the `.env.example` template exists. The current process has no `BAA_P7_*` credential variables. Template values were not treated as authorization or credentials.
- `docker compose config --services` cannot resolve in the current process because required Compose variables are unset. No `.env` was created and no container was started or changed.
- No verifiable four-source staging inventory, time-bounded read-only authorization, read-only identity/credential-scope proof, named operator and private contact route covering the full window, independent stop and pilot-credential revocation path, or restricted evidence-storage approval was supplied for this run. The frozen readiness gate is therefore unmet.

These omissions prohibit the live preflight and four-hour observation. “No requests” is not reported as a 0% error rate or a healthy service result.

### Implementation

- Added the separate entry point `real_e2e/p7_internal_readonly_pilot.py`: fixed four-source order, `GET` only, at most one attempt per slot, and a three-second request timeout. Missing/weakened/drifting Runtime capability contracts fail closed; drift stops before the next source request. Redirects are not followed. Response bodies, full URLs, credentials, and employee data are not persisted.
- The window is bound to fixed UTC start/end values in an external activation record and measured with a monotonic clock: one round every 60 seconds, 240 rounds, 960 slots. Early-stop and unattempted slots remain in the denominator. The existing `p7_shadow_readonly.py` limit of 900 seconds / 300 rounds is unchanged.
- Activation requires external references and attestations for authorization, accountability, inventory, read-only scope, stop/revocation, and evidence handling. Exact paths and realm are checked; bearer-authenticated resources must use HTTPS. Required credentials are read only from `BAA_P7_RUNTIME_TOKEN`, `BAA_P7_KEYCLOAK_BEARER_TOKEN`, and `BAA_P7_ODOO_BEARER_TOKEN` when applicable; values are never printed. None are present in the current process.
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

- Focused unittest suite: **11/11 passed**. Coverage includes a simulated 240-round/960-slot window, unknown followed by two-round reacquisition, stopping after the 300-second reacquisition budget expires, immediate stop on capability drift, manual STOP, operator loss, cost overrun, activation path and HTTPS checks, hash-bound preflight evidence, slot/event hash chains and checkpoint reconciliation, error-detail redaction, and preservation of the legacy 900-second limit.
- The frozen-contract static checker passed; the observer's direct `--help` entry point passed.
- The full-window test used a simulated clock and local fake responses. It is **not** a four-hour staging run and does not prove remote service availability or authorization.
- The preregistered JSON and thresholds were not changed. Any live acceptance decision still requires external authorization, real observations, and independent review.

### Required before real execution

The operator must provide a valid private activation record, approved exact four-source inventory, read-only HTTPS credentials and restricted evidence storage, and confirm the named owner/operator, full-window coverage, private contact, independent stop/revocation path, and evidence access/14-day retention approval. Then run the short `preflight` within its approved window. Only if it qualifies may `observe` be started manually with the same code and inventory binding. If any prerequisite cannot be verified, remain stopped and do not widen privileges.
