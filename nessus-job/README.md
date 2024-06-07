# Nessus Data Exporter
Instruction to export Nessus Data to AccuKnox SaaS

### Prerequisites:
- Docker
- Parameters as env variable to get details from Nessus
- Parameters env variable to send details to AccuKnox SaaS


### Parameters:
| Variable             | Sample Value                   | Description                            |
| -------------------- | ------------------------------ | -------------------------------------- |
| nessus_url           | https://cloud.tenable.com      | Tenable Nessus Server URL              |
| folder_id            | 4                              | Nessus Folder ID                       |
| nessus_access_key    | $access_key                    | Nessus Access Key                      |
| nessus_secret_key    | $secret_key                    | Nessus Secret Key                      |
| k8s_job              | false                          | This is required when ran outside SaaS |
| IS_ONPREM_DEPLOYMENT | true                           | This is required when run outside SaaS |
| CSPM_BASE_URL        | https://cspm.demo.accuknox.com | AccuKnox CSPM API Endpoint             |
| label                | NESSUS                         | AccuKnox Label                         |
| internal_tenant_id   | $tenant_id                     | AccuKnox Tenant ID                     |
| ARTIFACT_TOKEN       | $token                         | AccuKnox Token                         |

> All variables are mandatory

## Steps to send details to SaaS:
1. Creating and Switching to `/tmp/nessus-output/` folder to store nessus file on local.
```sh
mkdir -p /tmp/nessus-output/ && cd /tmp/nessus-output/
```

2. Getting Nessus data & Sending data to AccuKnox SaaS
```bash
docker run --rm -it \
    -e nessus_url=https://cloud.tenable.com \
    -e folder_id=4 \
    -e nessus_access_key=$access_key  \
    -e nessus_secret_key=$secret_key \
    -e k8s_job=false \
    -e IS_ONPREM_DEPLOYMENT=true \
    -e CSPM_BASE_URL=https://cspm.demo.accuknox.com \
    -e label=NESSUS \
    -e internal_tenant_id=$tenant_id \
    -e ARTIFACT_TOKEN=$token \
    -v $PWD:/tmp/ \
    accuknox/nessus:v1
```

> Note: If we don't want to store data inside `/tmp/nessus-output/` then step #1 can be skipped and from step #2 last 2nd like i.e., `-v $PWD:/tmp/ \` can be removed.

### QnA:
- You might see a warning related to the Certificate, but this should not cause any issue
- If env variables are not correct, then this might not work correctly
