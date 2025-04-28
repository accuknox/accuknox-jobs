# 🔍 Checkmarx SAST Docker Job

This Docker job runs a Checkmarx scan and generates report files in JSON format, which can later be uploaded to the AccuKnox Management Portal.

## 🚀 Usage

```bash
rm -f Checkmarx-*.json # Remove existing reports (optional cleanup)

docker run --rm -it \
  -e API_KEY=eIGNiD384Tg \
  -e PROJECT_NAME=Accuknox/checkmarx \
  -e REPORT_PATH=/app/data/ \
  -v $PWD:/app/data/ \
  accuknox/checkmarxjob:1.0.4
```

> This will generate `Checkmarx-*.json` files in the current directory, one per project/component found.

---

## ⚙️ Configuration

| Environment Variable | Sample Value                             | Description                                          |
|----------------------|------------------------------------------|------------------------------------------------------|
| `API_KEY`*           | `eIGNiD384Tg`                            | API key token to authenticate with Checkmarx API     |
| `PROJECT_NAME`*      | `Accuknox/checkmarx`                     | Name of the Checkmarx project                        |
| `REPORT_PATH`        | `/app/data/`                             | Directory to save the generated JSON reports         |

> **Note:** Variables marked with `*` are mandatory.

---

## 📤 Upload Reports to AccuKnox Management Portal

Once the scan is complete and reports are generated, use the following script to upload them to the AccuKnox Management Plane:

```bash
TENANT_ID="<tenant ID>" # e.g., 19
LABEL="<label>" # e.g., SAST
AK_URL="<AccuKnox CSPM URL>" # e.g., cspm.demo.accuknox.com
AK_TOK=<artifact token received from accuknox management plane>

for file in `ls -1 Checkmarx-*.json`; do
  curl --location "https://$AK_URL/api/v1/artifact/?tenant_id=$TENANT_ID&data_type=CX&save_to_s3=True&label_id=$LABEL" \
       --header "Tenant-Id: $TENANT_ID" \
       --header "Authorization: Bearer $AK_TOK" \
       --form "file=@"$file""
done
```
