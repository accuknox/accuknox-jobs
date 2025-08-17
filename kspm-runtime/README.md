# KSPM Runtime Helm Chart

The **kspm-runtime** Helm chart consolidates multiple AccuKnox and third-party charts (agents, jobs, and security operators) into a single, parameterized deployment.

---

## Dependencies

| Chart | Version | Condition |
|-------|---------|-----------|
| agents-chart | v0.10.8-test | `global.agents.enabled` |
| kubearmor-operator | v1.5.7 | `kubearmor-operator.enabled` |
| cis-k8s-job | 0.1.0 | `global.cis.enabled` |
| k8s-risk-assessment-job | 0.1.0 | `global.riskassessment.enabled` |
| kiem-job | 0.1.0 | `global.kiem.enabled` |
| knoxguard-chart | v0.2.1 | `admissionController.enabled` |
| kyverno | 3.3.7 | `kyverno.enabled` |

---

## Key Parameters

| Key | Description |
|-----|-------------|
| `global.agents.enabled` | Enable agents |
| `global.cis.enabled` | Enable CIS job |
| `global.riskassessment.enabled` | Enable risk assessment job |
| `global.kiem.enabled` | Enable KIEM job |
| `kubearmor-operator.enabled` | Enable KubeArmor operator |
| `admissionController.enabled` | Enable KnoxGuard admission controller |
| `kyverno.enabled` | Enable Kyverno |
| `global.clusterName` | Cluster name |
| `global.tenantId` / `global.authToken` | Tenant authentication |
| `global.enableJobsUrl` | Enable job URL reporting |

---

## Installation

```bash
git clone https://github.com/accuknox/accuknox-jobs.git
cd accuknox-jobs/kspm-runtime
helm dependency update

helm upgrade --install kspm-runtime ./ \
  -n kspm --create-namespace \
  --set global.agents.enabled=true \
  --set global.agents.joinToken="" \
  --set global.agents.url=<url> \
  --set global.cis.enabled=true \
  --set global.kiem.enabled=true \
  --set global.riskassessment.enabled=true \
  --set kyverno.enabled=true \
  --set admissionController.enabled=true \
  --set kubearmor-operator.enabled=true \
  --set kubearmor-operator.autoDeploy=true \
  --set global.enableJobsUrl=true \
  --set global.tenantId="" \
  --set global.authToken="" \
  --set global.clusterName="" \
  --set global.cronTab="" \
  --set global.label=""
```
---

## Notes

- Run ```helm dependency update``` before install/upgrade.
- Enable/disable sub-charts via boolean flags.
- Update sub-chart versions in ```Chart.yaml``` before tagging a release.