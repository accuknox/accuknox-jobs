# AccuKnox k8s-risk-asessment Job

A job for scanning cluster misconfiguration through kubescape

## Helm install

### Local

```
helm upgrade --install k8s-risk-assessment-job -n k8s-risk-assessment --create-namespace --set accuknox.authToken="TOKEN" .
```

### Published

```
helm upgrade --install k8s-risk-assessment-job oci://public.ecr.aws/k9v9d5v2/k8s-risk-assessment-job -n k8s-risk-assessment --create-namespace --set accuknox.authToken="TOKEN" .
```

where TOKEN is issued from AccuKnox SaaS.

### Configuration

| Helm key | Default Value | Description | Required |
|----------|---------------|-------------| -------- |
| accuknox.authToken | "NO-TOKEN-SET" | Auth token from AccuKnox SaaS | YES |
| accuknox.URL | "cspm.dev.accuknox.com" | URL of the environment | YES |
| accuknox.clusterName | "default" | name of the cluster | YES (auto-populated by SaaS) |
| accuknox.tenantID | "" | ID of AccuKnox tenant | YES (auto-populated by SaaS) |
| accuknox.cronTab | "0 */6 * * *" | cron tab for the job - timezone: UTC | NO |
| accunkox.label | "default" | label of the cluster | NO |
| kubescape.image.repository | "quay.io/kubescape/kubescape-cli" | kubescape image repo | NO |
| kubescape.image.tag | v3.0.8 | kubescape version - taken from appVersion by default | NO |
