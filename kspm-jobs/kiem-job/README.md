# AccuKnox KIEM

## Deploying AccuKnox KIEM as a Kubernetes Job

Follow these instructions to deploy AccuKnox KIEM as a Kubernetes job.

### Prerequisites:

- A running Kubernetes cluster
- [Helm (v3.13.1 or later)](https://v3.helm.sh/docs/intro/install/)

### Parameters:

| Variable             | Sample Value           | Description                |
|----------------------|------------------------|----------------------------|
| url                  | cspm.demo.com | AccuKnox CSPM Endpoint URL |
| tenantId             | 2                      | AccuKnox Tenant ID         |
| label                | KIEM                   | AccuKnox Label             |
| authToken            | $token                 | AccuKnox Token             |
| clusterName          | $clusterName           | Cluster Name               |
| cronTab              | 30 9 * * *             | CronJob (UTC)              |

### Clone GitHub and switch to KIEM job folder

```sh
git clone https://github.com/accuknox/accuknox-jobs
cd accuknox-jobs/kiem-job
```

### Helm command to deploy the AccuKnox KIEM Kubernetes job locally:

```sh
helm upgrade --install accuknox-kiem . \
    --set url="cspm.demo.com" \
    --set tenantId="$tenantId" \
    --set label="$label" \
    --set authToken="$token" \
    --set clusterName="$clusterName" \
    --set cronTab="30 9 * * *"
```

### Notes:

- You can obtain the AccuKnox Token and Tenant ID from the AccuKnox
  SaaS platform under `Settings > Tokens`.
- The AccuKnox Label can be found on the AccuKnox SaaS platform under
  `Settings > Labels`.

## Manual Procedure

Follow these instructions to run AccuKnox KIEM manually, outside of
Kubernetes.

### Prerequisites:

- `kubeconfig` file located at `$HOME/.kube`
- A running Kubernetes cluster
- [Docker](https://docs.docker.com/engine/install/)
- curl

### Generate a report:

```sh
mkdir -p data
docker run \
    --network host \
    -v ./data:/data \
    -v "$HOME/.kube:/root/.kube" \
    accuknox/kiem:latest \
    ./kiem run --output /data/report.json
```

### Push the report to AccuKnox SaaS:

```sh
export URL="<AccuKnox CSPM URL>" # e.g., cspm.demo.com
export TENANT_ID="<tenant ID>"
export LABEL_NAME="<label>"
export AUTH_TOKEN="<auth token>"

curl -L -X POST \
    -H "Tenant-Id: ${TENANT_ID}" \
    -H "Authorization: Bearer ${AUTH_TOKEN}" \
    -F file=@data/report.json \
    "https://${URL}/api/v1/artifact/?tenant_id=${TENANT_ID}&data_type=KIEM&save_to_s3=false&label_id=${LABEL_NAME}"
```
