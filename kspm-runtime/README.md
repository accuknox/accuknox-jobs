# KSPM Runtime Helm Chart

The **kspm-runtime** Helm chart consolidates multiple AccuKnox and third-party charts (agents, jobs, and security operators) into a single, parameterized deployment.

---

## Dependencies

| Chart | Version | Condition |
|-------|---------|-----------|
| agents-chart | v0.11.23 | `global.agents.enabled` |
| kubearmor-operator | v1.6.6 | `global.kubearmor.enabled` |
| cis-k8s-job | 0.1.0 | `global.cis.enabled` |
| k8s-risk-assessment-job | 0.1.0 | `global.riskassessment.enabled` |
| kiem-job | 0.1.0 | `global.kiem.enabled` |
| knoxguard-chart | v0.2.3 | `admissionController.enabled` |
| kyverno | 1.16.2 | `kyverno.enabled` |
| kubeshield-chart | v0.3.5 | `global.inClusterScan.enabled` |
| opencost (alias: costmanager) | 2.5.33-accuknox.1 | `global.costManager.enabled` |

---

## Key Feature Flags

| Variable | Description |
|-----|-------------|
| `global.agents.enabled` | Enable agents |
| `global.enableJobsUrl` | Enable job URL reporting |
| `global.cis.enabled` | Enable CIS job |
| `global.riskassessment.enabled` | Enable risk assessment job |
| `global.kiem.enabled` | Enable KIEM job |
| `global.kubearmor.enabled` | Enable KubeArmor operator |
| `admissionController.enabled` | Enable KnoxGuard admission controller |
| `kyverno.enabled` | Enable Kyverno |
| `global.inClusterScan.enabled` | Enable kubeshield-chart |
| `global.costManager.enabled` | Install OpenCost for cost management (default: false) |
| `costmanager.customPricing.enabled` | Override provider pricing with custom rates (default: false) |

## Global Configuration Parameters
### AccuKnox Connectivity

| Variable             | Sample Value           | Description                |
|----------------------|------------------------|----------------------------|
| global.agents.url    | stage.accuknox.com          | AccuKnox CSPM Endpoint URL |
| global.agents.joinToken    | $join-token          | Agent Join Token |
| global.agents.accessKey    | $accesskey          | Agent Access Keys |
| global.authToken            | $token                 | AccuKnox API Token |
| global.tenantId             | 2                      | AccuKnox Tenant ID         |
| global.clusterName          | cluster           | Cluster Name               |
| global.label                | KIEM                   | AccuKnox Label             |

### Registry Configuration

| Variable             | Sample Value           | Description                |
|----------------------|------------------------|----------------------------|
| global.registry.url    | public.ecr.aws/k9v9d5v2             | Private registry URL |
| global.registry.secretName    | secrets          | Image pull secret name |
| global.registry.username    | admin          | Registry username |
| global.registry.password    | password          | Registry password |
| global.registry.preserveUpstream    | false          | Preserve upstream images |

### Deployment Options

| Variable             | Sample Value           | Description                |
|----------------------|------------------------|----------------------------|
| global.SingleEndpointDeployment    | true         | On-prem IP based deployment |
| global.airgapped    | true          | Air-gapped installation mode (k8s-risk-assessment job) |
| global.certEnabled    | true/false          | Set this for cert need to be enabled |
| global.certSecretName    | random name      | if we enable cert, we need to install a secret with the cert |
| global.certPath    | /path/to/cert          | Local certificate path |
| global.certURL    | https://cert-url/        | Remote certificate URL |
| global.skipTLSVerification    | false          | To skip TLS verification |
| global.cronTab              | 30 9 * * *             | CronJob (UTC)              |

### Tool Configuration (CIS)

| Variable             | Sample Value           | Description                |
|----------------------|------------------------|----------------------------|
| global.cis.toolConfig.platform   | "GKE" / "AKS"                    | Name of the platform. Default: empty |
| global.cis.toolConfig.nodeType   | master OR controlplane            | For node selection                   |
| global.cis.toolConfig.targets    | "master,controlplane,node"        | [Ref](https://github.com/aquasecurity/kube-bench/blob/main/docs/flags-and-commands.md#specifying-benchmark-sections) |
| global.cis.toolConfig.benchmark  | "gke-1.6.0" | [Ref](https://github.com/aquasecurity/kube-bench/blob/main/docs/platforms.md) |
| global.cis.toolConfig.check | "1.1.1,1.2.3"     | Control IDs to check |
| global.cis.toolConfig.skip | "1.1.1,1.3.1" | Control IDs to skip |
---

## Installation

```bash
git clone https://github.com/accuknox/accuknox-jobs.git
cd accuknox-jobs
helm dependency update

helm upgrade --install agents kspm-runtime \
  -n agents --create-namespace \
  --set global.agents.enabled=true \
  --set global.agents.joinToken="" \
  --set global.agents.url="" \
  --set kyverno.enabled=true \
  --set admissionController.enabled=true \
  --set kubearmor.enabled=true \
  --set global.autoDeploy=true \
  --set global.enableJobsUrl=true \
  --set global.kiem.enabled=true \
  --set global.riskassessment.enabled=true \
  --set global.cis.enabled=true \
  --set global.tenantId="" \
  --set global.authToken="" \
  --set global.clusterName="" \
  --set global.cronTab="" \
  --set global.label="" \
  --set global.inClusterScan.enabled=true \
```
---

## Notes

### OpenCost cost manager

For the complete change history, implementation details, validation, and future
maintenance instructions, see [OPENCOST-IMPLEMENTATION.md](../OPENCOST-IMPLEMENTATION.md).

#### Cloud clusters with custom pricing disabled

With `global.costManager.enabled=true` and
`costmanager.customPricing.enabled=false`, OpenCost detects the cloud
provider at runtime from Kubernetes nodes. No cloud selection flag is required
for this detection:

| Cluster | Upstream detection | Pricing provider |
|---|---|---|
| EKS | Node provider ID starts with `aws`, or kubelet version contains `eks` | AWS |
| AKS | Node provider ID starts with `azure` | Azure |
| OKE | Node provider ID starts with `ocid` | Oracle |

Source: [OpenCost 1.121.3 provider detection](https://github.com/opencost/opencost/blob/v1.121.3/pkg/cloud/provider/provider.go).
The optional custom-provider environment reference is unset when the pricing
ConfigMap is absent, preserving automatic detection. Cloud pricing is an
estimate, not necessarily the customer's negotiated or invoiced rate. Public
pricing endpoints must be reachable, node types/regions must be recognized,
and provider-specific permissions/configuration may be needed for additional
billing features. AWS network pricing still uses configured/default rates.
An unsupported or unrecognized provider falls back to the default provider.

#### One command generated by the onboarding UI

The UI should append the following arguments to the existing agent installation
command, keeping all currently selected agent/job settings in that same command:

| UI field | Helm argument |
|---|---|
| Cost manager toggle | `--set global.costManager.enabled=true` or `false` |
| Custom pricing toggle | `--set costmanager.customPricing.enabled=true` or `false` |
| Currency | `--set-string costmanager.customPricing.costModel.currencyCode=INR` (default: USD) |
| CPU | `--set-string costmanager.customPricing.costModel.CPU=<rate>` |
| RAM | `--set-string costmanager.customPricing.costModel.RAM=<rate>` |
| Storage | `--set-string costmanager.customPricing.costModel.storage=<rate>` |
| GPU | `--set-string costmanager.customPricing.costModel.GPU=<rate>` |
| Network: zone egress | `--set-string costmanager.customPricing.costModel.zoneNetworkEgress=<rate>` |
| Network: region egress | `--set-string costmanager.customPricing.costModel.regionNetworkEgress=<rate>` |
| Network: internet egress | `--set-string costmanager.customPricing.costModel.internetNetworkEgress=<rate>` |

Show the pricing fields when both toggles are enabled. Validate rates as finite,
nonnegative decimal numbers, allowing zero, and require all seven fields before
generating a custom-pricing command. Append rates only when custom pricing is
enabled. Always emit both toggle values explicitly so rerunning the generated
command can disable a previously enabled feature. Do not use `--reuse-values`;
emit the complete UI configuration on every install/upgrade. Spot rates can be
exposed separately through `spotCPU` and `spotRAM` if required; otherwise the
upstream example spot rates remain in the custom model.

For example, the UI generates this **single command** with the customer's
selected values (the prices below are examples):

```bash
helm upgrade --install agents oci://public.ecr.aws/k9v9d5v2/kspm-runtime \
  --version "$AGENTS_CHART_VERSION" \
  -n agents --create-namespace \
  --set global.agents.enabled=true \
  --set-string global.agents.joinToken="$JOIN_TOKEN" \
  --set-string global.agents.url="stage.accuknox.com" \
  --set-string global.clusterName="aadil-k3s" \
  --set global.costManager.enabled=true \
  --set costmanager.customPricing.enabled=true \
  --set-string costmanager.customPricing.costModel.CPU="0.031611" \
  --set-string costmanager.customPricing.costModel.RAM="0.004237" \
  --set-string costmanager.customPricing.costModel.storage="0.00005479452" \
  --set-string costmanager.customPricing.costModel.GPU="0.95" \
  --set-string costmanager.customPricing.costModel.zoneNetworkEgress="0.01" \
  --set-string costmanager.customPricing.costModel.regionNetworkEgress="0.01" \
  --set-string costmanager.customPricing.costModel.internetNetworkEgress="0.12"
```

The UI must replace the version and token placeholders with the actual release
and join token. The chart version must be a **published parent chart containing
this OpenCost dependency**; existing published versions do not acquire these
changes automatically. The release pipeline builds/packages dependencies before
publishing, so customers using that OCI chart do not run `helm dependency build`
or install OpenCost separately. Changing prices in the UI regenerates the same
command; the customer reruns it to upgrade the existing release. UI edits alone
do not change a running cluster. This repository contains Helm charts, not the
onboarding UI implementation.

The downloaded OpenCost chart is vendored in `../helm-charts/opencost` with
version `2.5.33-accuknox.1` and Helm alias `costmanager`. Its values are flattened
so pricing arguments are `costmanager.customPricing.*` and storage arguments
are `costmanager.exporter.persistence.*`. Templates read these flattened values;
resource definitions and image versions remain from upstream. The recorded
adaptation is `../helm-charts/opencost/accuknox-values-flattening.patch`.
`costmanager.nameOverride: opencost` preserves resource names and selectors,
including the existing PVC. Replace previous `costmanager.opencost.*` or
`opencost.opencost.*` arguments with `costmanager.*` when upgrading.

The original [OpenCost Helm chart](https://github.com/opencost/opencost-helm-chart)
archive is retained unchanged at `../helm-charts/upstream/opencost-2.5.33.tgz`
(OpenCost 1.121.3), downloaded from the official release with SHA-256:
`b5f9599dd8952fd0421632a035a3e2d8f01ea9583140043760eaeeaabe5f610f`.
Dependency updates package the local adaptation, preserving the flattened
interface instead of overwriting it with the upstream values layout.
The parent `values.yaml` configures its native collector data source and a 10Gi
ReadWriteOnce PVC mounted at `/mnt/export`. Prometheus sources and ServiceMonitor
are disabled; no Prometheus installation is required. A default StorageClass or
an explicit `costmanager.exporter.persistence.storageClass` is required.
The deployment uses one replica and an update strategy with zero surge pods
for PVC attachment.

```bash
helm dependency build kspm-runtime
helm upgrade --install agents ./kspm-runtime \
  -n agents --create-namespace \
  --set global.costManager.enabled=true
```

Add `--set costmanager.customPricing.enabled=true` and pass your actual
rates in a values file to override pricing. The included rates are upstream
examples, not a pricing recommendation. All custom rates use the same currency.
Set `costmanager.customPricing.costModel.currencyCode=INR` for INR rates.
OpenCost supports the `currencyCode` field in its pricing model; the chart writes
it into the custom pricing ConfigMap. The default is USD. Selecting INR does
not convert dollar rates: enter CPU, RAM, storage, GPU, spot, and network rates
in INR yourself. This setting configures custom pricing when its toggle is enabled.

| Rate under `costmanager.customPricing.costModel` | Unit |
|---|---|
| `CPU` / `spotCPU` | Per CPU core-hour |
| `RAM` / `spotRAM` | Per GiB-hour |
| `GPU` | Per GPU-hour |
| `storage` | Per GiB-hour |
| `zoneNetworkEgress` | Per GiB of cross-zone egress |
| `regionNetworkEgress` | Per GiB of cross-region egress |
| `internetNetworkEgress` | Per GiB of internet egress |

OpenCost represents network pricing with these three egress rates; it has no
single `Network` pricing key. Configuring rates does not install a network
traffic collector; network cost reporting requires compatible network metrics.
Custom pricing creates an upstream ConfigMap and selects the custom provider
through `USE_CUSTOM_PROVIDER`, including on cloud-managed clusters. Keep
`customPricing.configmapName` and the exporter environment ConfigMap reference
in sync if you rename it. Leave `CustomPricesEnabled: "true"` in the custom model.
For multiple releases in the same namespace, give each pricing ConfigMap a
unique name and update its environment reference.

```yaml
global:
  costManager:
    enabled: true
costmanager:
  customPricing:
    enabled: true
    costModel:
      currencyCode: USD
      CPU: "0.031611"
      RAM: "0.004237"
      GPU: "0.95"
      storage: "0.00005479452"
      zoneNetworkEgress: "0.01"
      regionNetworkEgress: "0.01"
      internetNetworkEgress: "0.12"
```

Install with `helm upgrade --install agents ./kspm-runtime -n agents
--create-namespace -f your-cost-values.yaml`. Rates should be quoted strings.
Disabling cost management removes the subchart resources, including its PVC;
volume retention follows your StorageClass reclaim policy. Back up required
history before disabling it or uninstalling the release.

- Run ```helm dependency update``` before install/upgrade.
- Enable/disable sub-charts via boolean flags.
- Update sub-chart versions in ```Chart.yaml``` before tagging a release.
