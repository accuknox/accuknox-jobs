# 

```
docker run --rm -it -e SQ_URL=http://35.188.10.229:9000 -e SQ_AUTH_TOKEN=<AUTH-TOKEN> -e SQ_PROJECTS="^nimbus$" -e REPORT_PATH=/app/data/ -v $PWD:/app/data/ accuknox/sastjob:latest
```

Configuration
|      Var       | Sample Value              | Description                        |
|----------------|---------------------------|------------------------------------|
| SQ_URL*        | http://35.188.10.229:9000 | SonarQube server URL               |
| SQ_AUTH_TOKEN* | squ_token                 | SonarQube user authn token         |
| SQ_PROJECTS    | "^nimbus$"                | Scan the given projects/components |
| REPORT_PATH    | /app/data/                | Path to keep the report json files |

> * are mandatory configuration options
