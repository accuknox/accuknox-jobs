# KSPM Runtime Helm Chart

The **kspm-runtime** Helm chart consolidates multiple AccuKnox and third-party charts (agents, jobs, and security operators) into a single, parameterized deployment.

---

## Dependencies

| Chart | Version | Condition |
|-------|---------|-----------|
| agents-chart | v0.11.13 | `global.agents.enabled` |
| kubearmor-operator | v1.5.7 | `kubearmor-operator.enabled` |
| cis-k8s-job | 0.1.0 | `global.cis.enabled` |
| k8s-risk-assessment-job | 0.1.0 | `global.riskassessment.enabled` |
| kiem-job | 0.1.0 | `global.kiem.enabled` |
| knoxguard-chart | v0.2.1 | `admissionController.enabled` |
| kyverno | 3.3.7 | `kyverno.enabled` |
| kubeshield-chart | v0.2.5 | `global.inClusterScan.enabled` |

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
| `global.inClusterScan.enabled` | Enable kubeshield-chart |
| `cleanup.enabled` | Enable automatic cleanup of all CRDs and cluster resources on uninstall (default: true) |

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

## Uninstallation

To uninstall the chart and clean up all resources including CRDs and ClusterRoleBindings:

```bash
helm uninstall kubeshield -n kubeshield
```

The chart includes a pre-delete hook that automatically cleans up:
- **Kubeshield CRDs**: `clusterscans`, `discoveries`, `imagescans`, `scheduleclusterscans`
- **KubeArmor CRDs**: `kubearmorpolicies`, `kubearmorhostpolicies`, `kubearmorclusterpolicies`, `kubearmorconfigs`
- **KubeArmor ClusterRoleBindings and ClusterRoles**
- **KubeArmor namespace** (if different from the release namespace)

### Disabling Automatic Cleanup

If you want to disable automatic cleanup (e.g., to preserve CRDs for other workloads):

```bash
helm upgrade --install kubeshield ./kspm-runtime \
  --set cleanup.enabled=false \
  [other flags...]
```

### Manual Cleanup (if needed)

If automatic cleanup fails or is disabled, you can manually remove resources:

```bash
# Delete Kubeshield CRDs
kubectl delete crd clusterscans.kubeshield.accuknox.com
kubectl delete crd discoveries.kubeshield.accuknox.com
kubectl delete crd imagescans.kubeshield.accuknox.com
kubectl delete crd scheduleclusterscans.kubeshield.accuknox.com

# Delete KubeArmor CRDs
kubectl delete crd kubearmorpolicies.security.kubearmor.com
kubectl delete crd kubearmorhostpolicies.security.kubearmor.com
kubectl delete crd kubearmorclusterpolicies.security.kubearmor.com
kubectl delete crd kubearmorconfigs.operator.kubearmor.com

# Delete KubeArmor ClusterRoleBindings
kubectl delete clusterrolebinding kubearmor-operator-clusterrolebinding
kubectl delete clusterrolebinding kubearmor-clusterrolebinding
kubectl delete clusterrolebinding kubearmor-relay-clusterrolebinding

# Delete KubeArmor ClusterRoles
kubectl delete clusterrole kubearmor-operator-clusterrole
kubectl delete clusterrole kubearmor-clusterrole
kubectl delete clusterrole kubearmor-relay-clusterrole

# Delete KubeArmor namespace
kubectl delete namespace kubearmor
```

---

## Notes

- Run ```helm dependency update``` before install/upgrade.
- Enable/disable sub-charts via boolean flags.
- Update sub-chart versions in ```Chart.yaml``` before tagging a release.
- The cleanup job uses `bitnami/kubectl:latest` image - ensure your cluster can pull from Docker Hub or configure an alternate image registry.
