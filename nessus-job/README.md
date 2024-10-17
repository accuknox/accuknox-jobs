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

## Steps to send details to SaaS (Manual):
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

## Steps to send details to SaaS (Schedule):
1. Create a `.env` file. This file should contain your environment variables in this format:
```sh
nessus_url=https://cloud.tenable.com
folder_id=4
nessus_access_key=$access_key
nessus_secret_key=$secret_key
CSPM_BASE_URL=https://cspm.demo.accuknox.com
label=$label
internal_tenant_id=$tenant_id
ARTIFACT_TOKEN=$token
```

2. Use `crontab -e` to schedule Nessus Data Exporter  per your use case.
```sh
30 9 */2 * * docker run --rm --env-file $HOME/.env accuknox/nessus:v1
```

3. Breakdown of the above command, where
 - `30 9 */2 * *` is schedule in [Cron](https://crontab.guru/#30_9_*/2_*_*) that will execute scan at 09:30 on every 2nd day-of-month.
 - `--env-file` is for prerequisite parameters as docker environment variables. Provide the file path you've used in Step #1.
