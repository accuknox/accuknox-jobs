# 🔍 Checkmarx SAST Docker Job

This Docker job performs a Checkmarx SAST scan and generates report files in JSON format using Checkmarx's OAuth-based authentication.

## 🚀 Usage

Use your Checkmarx credentials and OAuth parameters to authenticate and run the scan. This tool saves the results in the current directory.

### 🐳 Docker Run Example

```bash
docker run --rm -it \
  -e PROJECT_NAME="Accuknox/checkmarx" \
  -e BASE_URL="https://accuknox.checkmarx.net" \
  -e USER_NAME="admin" \
  -e PASSWORD="yourpassword" \
  -v $PWD:/app/data/ \
  accuknox/checkmarxsastjob:1.1


> This will generate `Checkmarx-*.json` files in the current directory, one per project/component found.

---

## ⚙️ Configuration

| Environment Variable | Sample Value                             | Description                                          |
| ---------------- | -------------------------------------- | -------------------------------------------------------- |
| `PROJECT_NAME`\* | `Accuknox/checkmarx`                   | Name of the Checkmarx project to scan                    |
| `BASE_URL`\*     | `https://accuknox.checkmarx.net`    | Base URL for the Checkmarx API                           |
| `USER_NAME`\*    | `admin`                                | Username for Checkmarx login (used for token generation) |
| `PASSWORD`\*     | `yourpassword`                         | Password for Checkmarx login (used for token generation) |
| `SCOPE`          | `sast_rest_api`                        | OAuth scope used for token generation ( default: `sast_rest_api` ) |
| `GRANT_TYPE`     | `password`                             | OAuth grant type ( default: `password` )                   |
| `CLIENT_ID`      | `resource_owner_client`                | OAuth client ID ( default: `resource_owner_client` )       |
| `CLIENT_SECRET`  | `014DF517-39D1-4453-B7B3-9930C563627C` | OAuth client secret  ( default: `014DF517-39D1-4453-B7B3-9930C563627C` ) |

> **Note:** Variables marked with `*` are mandatory.



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
