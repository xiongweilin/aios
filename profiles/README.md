# AIOS release profiles

`aios-profile.schema.json` defines the compatibility-tested composition consumed by the public Manager.

Create `stable.json` only after every required owner repository has published versioned Windows artifacts and the composition has passed its compatibility checks. Each component entry must identify its owner repository, immutable release tag, exact asset URL, and SHA-256. The validation record must link to the passing AIOS integration run. A usable public Setup also requires an explicit lifecycle-readiness gate after install/update/start/stop/repair/uninstall have end-to-end coverage.

Do not use `latest`, branch archives, source checkouts, or invented versions/digests. The profile is owned by `xiongweilin/aios`; component code and artifacts remain owned by their respective repositories. Until a valid `stable.json` exists, Setup may be built for engineering verification but must not be published as a usable end-user release.
