# 🔍 Checkmarx ONE API Docker Job

This Docker job fetches **scan results** from [Checkmarx](https://www.checkmarx.com/) in JSON format and uploads them to the [AccuKnox](https://accuknox.com) SaaS portal.

## 🚀 Usage

### 1️⃣ Create a `.env` file
Add the required environment variables from **Configuration**  to a `.env` file in your working directory:

### 🐳 Docker Run Example

```bash
rm -f Checkmarx-*.json # Remove existing reports (optional cleanup)

docker run --rm -it \
  --env-file .env \
  -v $PWD:/app/data/ \
  accuknox/checkmarx-one-job:1.4
```

> This will generate `Checkmarx-*.json` files in the current directory, one per project/component found.

---

## ⚙️ Configuration

| Environment Variable | Sample Value                             | Description                                          |
|----------------------|------------------------------------------|------------------------------------------------------|
| `CX_API_KEY`*        | `eIGNiD384Tg`                            | API key token to authenticate with Checkmarx API     |
| `CX_PROJECT`*        | `{"Accuknox/checkmarx":"main"}`          | Comma-separated project names in format project:branch (e.g., `[{proj1:branch1},{proj2:branch2}]`). If a branch is not specified for a project, the latest scan across all branches will be used.                  |
| `CX_PRIMARY_BRANCH` | `true` or `false`                          | Retrieve project where primary branch is selected. Default value is `false`|
| `AK_ENDPOINT`\*      | `https://cspm.demo.accuknox.com`         | AccuKnox CSPM API Endpoint                               |
| `AK_LABEL`\*         | `$LABEL `                                | The label created in AccuKnox SaaS for associating scan results |
| `AK_TENANT_ID`\*     | `$TENANT_ID$`                            |  The ID of the tenant associated with the CSPM panel   |
| `AK_TOKEN`\*         | `$ARTIFACT_TOKEN`                        | The token for authenticating with the CSPM panel |

> **Note:** Variables marked with `*` are mandatory.

## ⚙️ Sample `.env` File
```
CX_API_KEY=eyJh....
CX_PROJECT={"*":"*","-*Ayush*":"*"}
CX_PRIMARY_BRANCH=true
AK_ENDPOINT=https://cspm.accuknox.com/
AK_LABEL=$label
AK_TENANT_ID=$tenant_id
AK_TOKEN=eyJ0....
```
> **Note:** This will Scan all Projects with All Branches except Project Starts with Ayush.

---
