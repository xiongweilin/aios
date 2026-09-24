# AIOS

This repository owns the AIOS Manager, Setup bootstrapper, and tested component-composition profile. Component implementation remains in its owner repositories; AIOS records immutable release versions and coordinates lifecycle.

## User installation

The public entry point is a single `AIOS-Setup.exe`. It installs the daily Manager separately from durable user data and creates Start Menu/Desktop shortcuts. The Manager and component binaries may be replaced; long-lived state remains under:

```text
%USERPROFILE%\.aios\
├─ config\
├─ state\
├─ data\
├─ logs\
├─ components\
└─ domains\
   ├─ autonomous-development\
   ├─ administrative\
   └─ ...
```

The Manager executable is installed under `%LOCALAPPDATA%\Programs\Metratio\AIOS\`. Uninstalling the Manager removes the program and shortcuts only; it does not delete `%USERPROFILE%\.aios`.

The Manager accepts `install`, `update`, `start`, `stop`, `status`, `logs`, `repair`, and `uninstall`. Installation and lifecycle actions are gated on a compatibility-validated profile. Each profile pins owner repository, release tag, asset URL, SHA-256, protocol contracts, and passing integration evidence. It never downloads a component's `latest` release.

**Release state:** owner repositories do not yet publish the required compatible Windows artifacts, so there is no `profiles/stable.json` and no usable public Setup release. The build can be exercised for engineering verification, but the release workflow blocks publication until the profile is complete and verified.

## Developer controller

The pre-existing source-checkout service controller is still available as `dist/aios-dev.exe` for development workstations. It remains separate from the public Manager and may use developer tools and checked-out project repositories. It is not included in `AIOS-Setup.exe` or GitHub Releases.

## Release profile ownership

`profiles/aios-profile.schema.json` defines the manifest contract. The profile is owned here; component artifacts are owned by each component's repository. Upgrade installs a tested profile version. Previous version directories remain available for rollback; repair uses the same pinned artifacts. User data and domain state remain outside replaceable component directories.

## Build

Requires Go 1.22+ and Windows PowerShell. Run from Windows:

```powershell
./build.ps1
```

This produces:

- `dist/AIOS-Setup.exe` — the only end-user release asset.
- `dist/aios.exe` — the public AIOS Manager embedded by Setup.
- `dist/aios-dev.exe` — developer-only source controller, never attached to a public release.
