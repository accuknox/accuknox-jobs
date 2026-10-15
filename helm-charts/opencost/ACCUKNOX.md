# AccuKnox costmanager values interface

This chart was extracted from the official OpenCost 2.5.33 release, not authored
from scratch. The original archive is retained in `../upstream` and its checksum
is recorded in `../../kspm-runtime/README.md`.

The local version is `2.5.33-accuknox.1`. The upstream `opencost` values block is
flattened into the chart root and matching template and test references are
updated. The parent aliases this dependency as `costmanager`, enabling:

```bash
--set costmanager.customPricing.enabled=true
--set-string costmanager.customPricing.costModel.CPU="0.04"
```

All seven pricing fields, collector settings, and persistence settings use this
same root interface. The original resource definitions and container images are
retained. The exact changes from upstream are recorded in
`accuknox-values-flattening.patch`. The upstream README is retained for provenance;
remove its `opencost.` values prefix when using this adaptation directly, or
replace that prefix with `costmanager.` when using the parent chart.

To update upstream, download and verify the new official archive, reapply the
flattening changes to values/templates/tests, update the local version and parent
dependency, and verify the rendered resources against upstream before release.
