# 🔍 Checkmarx SAST Docker Job

This Docker job fetches **SAST scan results** from [Checkmarx](https://www.checkmarx.com/) in JSON format and uploads them to the [AccuKnox](https://accuknox.com) SaaS portal.

## 🚀 Usage

### 1️⃣ Create a `.env` file
Add the required environment variables from **Configuration**  to a `.env` file in your working directory:

### 🐳 Docker Run Example

```bash
docker run --rm -it \
  --env-file .env \
  -v $PWD:/app/data/ \
  accuknox/checkmarxsastjob:1.3
```

> This will generate `Checkmarx-*.json` files in the current directory, one per project/component found.

---

## ⚙️ Configuration

| Environment Variable | Sample Value                           | Description                                        |
| ---------------- | -------------------------------------- | -------------------------------------------------------- |
| `CX_PROJECT_NAMES`\* | `Accuknox/checkmarx`                   | Comma-separated Checkmarx project names (e.g., org1/proj1,org2/proj2)                |
| `CX_BASE_URL`\*     | `https://accuknox.checkmarx.net`       | Base URL of the Checkmarx server                         |
| `CX_USER_NAME`\*    | `admin`                                | Username for Checkmarx login (used for token generation) |
| `CX_PASSWORD`\*     | `yourpassword`                         | Password for Checkmarx login (used for token generation) |
| `AK_ENDPOINT`\*| `https://cspm.demo.accuknox.com`       | AccuKnox CSPM API Endpoint                               |
| `AK_LABEL`\*        | `$LABEL `                              | The label created in AccuKnox SaaS for associating scan results |
| `AK_TENANT_ID`\*    | `$TENANT_ID$`                          |  The ID of the tenant associated with the CSPM panel   |
| `AK_TOKEN`\* | `$ARTIFACT_TOKEN`                    | The token for authenticating with the CSPM panel |
| `CX_SCOPE`          | `sast_rest_api`                        | OAuth scope used for token generation ( default: `sast_rest_api` ) |
| `CX_GRANT_TYPE`     | `password`                             | OAuth grant type ( default: `password` )                   |
| `CX_CLIENT_ID`      | `resource_owner_client`                | OAuth client ID ( default: `resource_owner_client` )       |
| `CX_CLIENT_SECRET`  | `014DF517-39D1-4453-B7B3-9930C563627C` | OAuth client secret  ( default: `014DF517-39D1-4453-B7B3-9930C563627C` ) |

> **Note:** Variables marked with `*` are mandatory.
