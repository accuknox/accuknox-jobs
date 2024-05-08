# AccuKnox k8s-risk-assessment Job

A job for scanning cluster misconfiguration through kubescape

## Helm install

### Local

```
cd k8s-risk-assessment-job
helm upgrade --install k8s-risk-assessment-job . \
-n k8s-risk-assessment --create-namespace \
--set accuknox.authToken="$TOKEN" \
--set accuknox.tenantID="$TENANT_ID" \
--set accuknox.clusterName="$CLUSTER_NAME" \
--set accuknox.URL="cspm.dev.accuknox.com"
```

### Published

```
helm upgrade --install k8s-risk-assessment-job oci://public.ecr.aws/k9v9d5v2/k8s-risk-assessment-job \
-n k8s-risk-assessment --create-namespace \
--set accuknox.authToken="$TOKEN" \
--set accuknox.tenantID="$TENANT_ID" \
--set accuknox.clusterName="$CLUSTER_NAME" \
--set accuknox.URL="cspm.dev.accuknox.com" \
--version="v0.4.0"
```

Where `version` can be taken from the [releases](https://github.com/accuknox/accuknox-jobs/releases) page

### Configuration

| Helm key | Default Value | Description | Required |
|----------|---------------|-------------| -------- |
| accuknox.authToken | "NO-TOKEN-SET" | Auth token from AccuKnox SaaS | YES (auto-populated by SaaS) |
| accuknox.URL | "cspm.demo.accuknox.com" | URL of the environment | YES (auto-populated by SaaS) |
| accuknox.clusterName | "" | name of the cluster | YES (auto-populated by SaaS) |
| accuknox.tenantID | "" | ID of AccuKnox tenant | YES (auto-populated by SaaS) |
| accuknox.clusterID | 0 | ID of the cluster | TBD |
| accuknox.cronTab | "30 9 * * *" | cron tab for the job - timezone: UTC | NO |
| accunkox.label | "" | label of the cluster | NO |
| kubescape.image.repository | "quay.io/kubescape/kubescape-cli" | kubescape image repo | NO |
| kubescape.image.tag | v3.0.8 | kubescape version - taken from appVersion by default | NO |
