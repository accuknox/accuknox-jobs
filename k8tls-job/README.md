# AccuKnox k8tls Job

## Helm install

```
helm upgrade --install k8tls-job . --set accuknox.authToken="TOKEN"
```
where TOKEN is issued from AccuKnox SaaS.

| Helm key | Default Value |
|----------|---------------|
| accuknox.authToken | "NO-TOKEN-SET" |
| accuknox.cronTab | "0 0/4 * * *" |
