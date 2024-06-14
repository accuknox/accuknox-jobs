# Nessus Data Exporter
Instruction to export Tenable Nessus Scan Data to AccuKnox SaaS.

### Prerequisites:
- [Docker](https://docs.docker.com/engine/install/)
- Parameters as docker environment variables to get scan file from [Tenable Nessus](https://www.tenable.com/products/nessus)
- Parameters as docker environment variables to send Nessus scan data to [AccuKnox](https://accuknox.com) SaaS

### Parameters:
| Variable             | Sample Value                   | Description                            |
| -------------------- | ------------------------------ | -------------------------------------- |
| nessus_url           | https://cloud.tenable.com      | Tenable Nessus Server URL              |
| folder_id            | 4                              | Nessus Folder ID                       |
| nessus_access_key    | $access_key                    | Nessus Access Key                      |
| nessus_secret_key    | $secret_key                    | Nessus Secret Key                      |
| CSPM_BASE_URL        | https://cspm.demo.accuknox.com | AccuKnox CSPM API Endpoint             |
| label                | $label                         | AccuKnox Label                         |
| internal_tenant_id   | $tenant_id                     | AccuKnox Tenant ID                     |
| ARTIFACT_TOKEN       | $token                         | AccuKnox Token                         |

## Steps to send details to SaaS:
1. Creating and switching to `/tmp/nessus-output/` folder to store Nessus scan file locally.
```sh
mkdir -p /tmp/nessus-output/ && cd /tmp/nessus-output/
```

2. Getting Nessus scan file & Sending data to AccuKnox SaaS
```bash
docker run --rm -it \
    -e nessus_url=https://cloud.tenable.com \
    -e folder_id=4 \
    -e nessus_access_key=$access_key  \
    -e nessus_secret_key=$secret_key \
    -e CSPM_BASE_URL=https://cspm.demo.accuknox.com \
    -e label=$label \
    -e internal_tenant_id=$tenant_id \
    -e ARTIFACT_TOKEN=$token \
    -v $PWD:/tmp/ \
    accuknox/nessus:v1
```

> Note: If we don't want to store data inside `/tmp/nessus-output/` then step #1 can be skipped and from step #2 last 2nd line i.e., `-v $PWD:/tmp/ \` can be removed.

### Note:
- All Docker environment variables are mandatory & case-sensitive.
