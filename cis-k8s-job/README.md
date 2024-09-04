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

---
## Manual Procedure
Instruction to perform CIS Benchmark manually using [kube-bench](https://github.com/aquasecurity/kube-bench) binary

### Prerequisites:
- [Kube-Bench](https://github.com/aquasecurity/kube-bench)
- [jq](https://jqlang.github.io/jq/download/)
- [Cluster Context](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_config/kubectl_config_use-context/)

### Steps to follow:
 - Getting output file as `results.json` on current-context of selected cluster
```sh
kube-bench run --config-dir ~/test/KubeBench/cfg/ --json --outputfile results.json
```
> Make sure you provide correct `--config-dir`.

 - Adding **Metadata** to above output file
```sh
cat <<<$(jq '. += {
    "Metadata": {
        "cluster_name":"$cluster",
        "label_name":"$label"}}
    ' results.json) >results.json
```
> Replace value of `$cluster` with cluster name & `$label` with AccuKnox Label

 - Sending output file to AccuKnox SaaS
```sh
curl --location --request POST 'https://cspm.demo.accuknox.com/api/v1/artifact/?tenant_id=$tenantId&data_type=KB&save_to_s3=false' --header 'Tenant-Id: $tenantId' --header "Authorization: Bearer $token" --form 'file=@"./results.json"'
```
> Replace value of `$tenantId` from AccuKnox Tenant ID & `$token` from AccuKnox Token

 - You should be able to see a successful message as **{"detail":"File received successfully"}**
