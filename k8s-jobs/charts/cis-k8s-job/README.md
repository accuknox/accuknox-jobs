# AccuKnox CIS K8s Job
Instruction to perform CIS Benchmark on Cluster via AccuKnox CIS K8s Job

### Prerequisites:
- [Docker](https://docs.docker.com/engine/install/)
- [Helm (v3.13.1 or later)](https://v3.helm.sh/docs/intro/install/)

### Parameters:
| Variable             | Sample Value           | Description                |
| -------------------- | ---------------------- | -------------------------- |
| accuknox.url         | cspm.demo.accuknox.com | AccuKnox CSPM Endpoint URL |
| accuknox.tenantId    | 2                      | AccuKnox Tenant ID         |
| accuknox.label       | CIS                    | AccuKnox Label             |
| accuknox.authToken   | $token                 | AccuKnox Token             |
| accuknox.clusterName | $clusterName           | Cluster Name               |
| accuknox.cronTab     | 30 9 * * *             | CronJob (UTC)              |

## Schedule CIS Job on cluster
#### Clone GitHub and switch to CIS K8s Job folder
```sh
git clone https://github.com/accuknox/accuknox-jobs.git && cd accuknox-jobs/cis-k8s-job
```

#### Helm Command to deploy AccuKnox CIS K8s Job locally:
```sh
helm upgrade --install accuknox-cis-k8s . \
    --set accuknox.url="cspm.demo.accuknox.com" \
    --set accuknox.tenantId="$tenantId" \
    --set accuknox.label="$label" \
    --set accuknox.authToken="$token" \
    --set accuknox.clusterName="$clusterName" \
    --set accuknox.cronTab="30 9 * * *"
```

### Note:
- You can get AccuKnox Token & Tenant ID from AccuKnox SaaS under navigation `Settings > Tokens`
- You can get AccuKnox Label from AccuKNox SaaS under navigation `Settings > Labels`
