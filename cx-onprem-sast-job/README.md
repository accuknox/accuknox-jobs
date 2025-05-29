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
  accuknox/checkmarxsastjob:1.2
```

> This will generate `Checkmarx-*.json` files in the current directory, one per project/component found.

---

## ⚙️ Configuration

| Environment Variable | Sample Value                           | Description                                        |
| ---------------- | -------------------------------------- | -------------------------------------------------------- |
| `PROJECT_NAME`\* | `Accuknox/checkmarx`                   | Comma-separated Checkmarx project names (e.g., org1/proj1,org2/proj2)                |
| `BASE_URL`\*     | `https://accuknox.checkmarx.net`       | Base URL of the Checkmarx server                         |
| `USER_NAME`\*    | `admin`                                | Username for Checkmarx login (used for token generation) |
| `PASSWORD`\*     | `yourpassword`                         | Password for Checkmarx login (used for token generation) |
| `CSPM_BASE_URL`\*| `https://cspm.demo.accuknox.com`       | AccuKnox CSPM API Endpoint                               |
| `LABEL`\*        | `$LABEL `                              | The label created in AccuKnox SaaS for associating scan results |
| `TENANT_ID`\*    | `$TENANT_ID$`                          |  The ID of the tenant associated with the CSPM panel   |
| `ARTIFACT_TOKEN`\* | `$ARTIFACT_TOKEN`                    | The token for authenticating with the CSPM panel |
| `SCOPE`          | `sast_rest_api`                        | OAuth scope used for token generation ( default: `sast_rest_api` ) |
| `GRANT_TYPE`     | `password`                             | OAuth grant type ( default: `password` )                   |
| `CLIENT_ID`      | `resource_owner_client`                | OAuth client ID ( default: `resource_owner_client` )       |
| `CLIENT_SECRET`  | `014DF517-39D1-4453-B7B3-9930C563627C` | OAuth client secret  ( default: `014DF517-39D1-4453-B7B3-9930C563627C` ) |

> **Note:** Variables marked with `*` are mandatory.
