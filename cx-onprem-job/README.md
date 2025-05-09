# 🔍 Checkmarx SAST Docker Job

This Docker job runs a Checkmarx scan and generates report files in JSON format, which can later be uploaded to the AccuKnox Management Portal.

## 🚀 Usage

Use your API key or login credentials to generate a valid Bearer token needed for authentication with the Checkmarx API. You can refer to [Checkmarx Authentication API documentation](https://checkmarx.stoplight.io/docs/checkmarx-one-api-reference-guide/branches/main/ywuqb5n3fas83-authentication-api) for details.

```bash
rm -f Checkmarx-*.json # Remove existing reports (optional cleanup)

docker run --rm -it \
  -e BEARER_TOKEN=eIGNiD384Tg \
  -e PROJECT_NAME=Accuknox/checkmarx \
  -e BASE_URL=https://deu.ast.checkmarx.net/api \
  -e REPORT_PATH=/app/data/ \
  -v $PWD:/app/data/ \
  accuknox/onpremcheckmarxjob:1.0.0
```

> This will generate `Checkmarx-*.json` files in the current directory, one per project/component found.

---

## ⚙️ Configuration

| Environment Variable | Sample Value                             | Description                                          |
|----------------------|------------------------------------------|------------------------------------------------------|
| `BEARER_TOKEN`*      | `eIGNiD384Tg`                            | API key token to authenticate with Checkmarx API     |
| `PROJECT_NAME`*      | `Accuknox/checkmarx`                     | Name of the Checkmarx project                        |
| `BASE_URL`*          | `https://deu.ast.checkmarx.net/api`      | Base URL of the Checkmarx API endpoint               |
| `REPORT_PATH`        | `/app/data/`                             | Directory to save the generated JSON reports         |

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
