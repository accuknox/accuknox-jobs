# 🔍 Checkmarx SAST Docker Job

This Docker job runs a Checkmarx scan and generates report files in JSON format, which can later be uploaded to the AccuKnox Management Portal.

## 🚀 Usage

```bash
rm -f Checkmarx-*.json # Remove existing reports (optional cleanup)

docker run --rm -it \
  -e ACCESS_TOKEN=eIGNiD384Tg \
  -e REGION=DEU \
  -e TENANT_NAME=accuknox-nfr \
  -e PROJECT_ID=2e973c17-c30b-4960-a3ef-e4916fd7eadc \
  -e REPORT_PATH=/app/data/ \
  -v $PWD:/app/data/ \
  accuknox/checkmarxjob:1.0.3
```

> This will generate `Checkmarx-*.json` files in the current directory, one per project/component found.

---

## ⚙️ Configuration

| Environment Variable | Sample Value                            | Description                                          |
|----------------------|------------------------------------------|------------------------------------------------------|
| `ACCESS_TOKEN`*       | `eIGNiD384Tg`                            | Access token to authenticate with Checkmarx API      |
| `REGION`*             | `DEU`                                    | Region code (e.g., `USA`, `DEU`)                     |
| `TENANT_NAME`*        | `accuknox-nfr`                           | Your AccuKnox tenant name                            |
| `PROJECT_ID`*         | `2e973c17-c30b-4960-a3ef-e4916fd7eadc`   | UUID of the Checkmarx project                        |
| `REPORT_PATH`         | `/app/data/`                             | Directory to save the generated JSON reports         |

> **Note:** Variables marked with `*` are mandatory.

---

## 📤 Upload Reports to AccuKnox Management Portal

Once the scan is complete and reports are generated, use the following script to upload them to the AccuKnox Management Plane:

```bash
TENANT_ID=2509
LABEL=SAST
AK_URL="cspm.demo.accuknox.com"
AK_TOK=<artifact token received from accuknox management plane>

for file in `ls -1 Checkmarx-*.json`; do
  curl --location "https://$AK_URL/api/v1/artifact/?tenant_id=$TENANT_ID&data_type=CX&save_to_s3=True&label_id=$LABEL" \
       --header "Tenant-Id: $TENANT_ID" \
       --header "Authorization: Bearer $AK_TOK" \
       --form "file=@"$file""
done
```
