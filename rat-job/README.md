# Risk Assessment Tool (RAT)

## Deploy Accuknox RAT as a job for VMs

Follow these instructions to deploy RAT as cronjob for VM clusters in Accuknox SAAS

### Using knoxctl 

knoxctl CLI can be installed using 
``` sh 
curl -sfL https://knoxctl.accuknox.com/install.sh | sudo sh -s -- -b /usr/local/bin
```

RAT can be installed in vm cluster using knoxctl cli. 

#### Parameters:

| Variable             | Sample Value           | Description                |
|----------------------|------------------------|----------------------------|
| url                  | cspm.dev.accuknox.com  | AccuKnox CSPM Endpoint URL |
| tenantId             | 24                     | AccuKnox Tenant ID         |
| label                | $label                 | AccuKnox Label             |
| authToken            | $token                 | AccuKnox Token             |
| clusterName          | $clusterName           | Cluster Name               |
| schedule             | 30 9 * * *             | CronJob (UTC)              |
| profile              | ubuntu20.04/rhel9      | profile for RAT tool       |
| benchmark            | stig                   | benchmark for RAT tool     |

#### knoxctl command to deploy RAT job
```sh
knoxctl onboard vm scanner \
  --version v0.8.3 \
  --profile ubuntu20.04 \
  --benchmark stig \
  --auth-token {{value}} \
  --cluster-name idt1 \
  --tenant-id 24 \
  --label {{value}} \
  --url cspm.dev.accuknox.com \
  --schedule "30 9 * * *"
```
in VM clusters RAT can be installed in 2 modes
1) As a docker container 
2) As a systemd service  

By default RAT is installed as docker container, to install it as a systemd service add `--vm-mode=systemd` flag to the above command.

## Manual Procedure

Follow these instructions to run AccuKnox RAT manually, without knoxctl.

On docker 

``` sh 
docker run --privileged --hostname=$(hostname) --pid=host --network=host -v /tmp:/host/tmp -v /:/host:rw --rm -it accuknox/rat:latest -p ubuntu20.04 -b stig --json 
```

Using binary 

- Download the RAT latest release from [here](https://github.com/accuknox/RAT/releases)
- Extract binary
- Run the following command
```sh
sudo ./rat analyze -p ubuntu20.04 -b stig --json 
```
### Pushing the report to SAAS 
``` sh
sudo ./rat analyze --auth-token $authtoken --url $url --label $label  --cluster-name $clustername --tenant-id $tenantId -p ubuntu20.04 -b stig --json
```



