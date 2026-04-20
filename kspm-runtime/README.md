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

- Run ```helm dependency update``` before install/upgrade.
- Enable/disable sub-charts via boolean flags.
- Update sub-chart versions in ```Chart.yaml``` before tagging a release.
