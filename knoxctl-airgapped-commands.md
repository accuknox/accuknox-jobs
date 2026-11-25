## Docker

### Download the bundle

```bash
wget -qO- "https://nbg1.your-objectstorage.com/accuknox-onprem-artifacts/kspm-runtime/airgapped-bundle/knoxctl-v0.9.59-vm-v0.12.7-linux-amd64-air-gapped.tar.gz" | tar -xz
```

### Install knoxctl

```bash
sudo install -m 0755 bin/knoxctl /usr/local/bin/knoxctl
```

### Onboard cp

```bash
sudo knoxctl onboard vm cp-node \
  --version=v0.12.7 \
  --vm-mode=docker \
  --from-source="$PWD/accuknox/v0.12.7" \
  --image-pull-policy=never \
  --force-recreate \
  --join-token=825cea79-b9fa-4be0-b9d6-e79e5076ab24 \
  --spire-host=spire.stage.accuknox.com:443 \
  --pps-host=pps.stage.accuknox.com:443 \
  --knox-gateway=knox-gw.stage.accuknox.com:443
```

### Onboard worker

```bash
sudo knoxctl onboard vm node \
  --version=v0.12.7 \
  --vm-mode=docker \
  --from-source="$PWD/accuknox/v0.12.7" \
  --image-pull-policy=never \
  --cp-node-addr="<CONTROL_PLANE_IP>"
```

### Install scheduled scanner

```bash
sudo knoxctl onboard vm scanner \
  --version=v0.12.7 \
  --vm-mode=docker \
  --from-source="$PWD/accuknox/v0.12.7" \
  --image-pull-policy=never \
  --enable-vmscan \
  --profile=ubuntu20.04 \
  --benchmark=stig \
  --auth-token="<AUTH_TOKEN>" \
  --cluster-name=vm \
  --tenant-id=5 \
  --label="<LABEL>" \
  --url=cspm.stage.accuknox.com \
  --schedule="0 4 * * *"
```

## Systemd

### Download the bundle

```bash
wget -qO- "https://nbg1.your-objectstorage.com/accuknox-onprem-artifacts/kspm-runtime/airgapped-bundle/knoxctl-v0.9.59-vm-v0.12.7-linux-amd64-air-gapped.tar.gz" | tar -xz
```

### Install knoxctl

```bash
sudo install -m 0755 bin/knoxctl /usr/local/bin/knoxctl
```

### Install RabbitMQ

```bash
sudo docker load --input rabbitmq.tar
sudo docker run -d --name knoxctl-rabbitmq --pull=never --restart=unless-stopped -p 5672:5672 -v knoxctl-rabbitmq-data:/var/lib/rabbitmq -e RABBITMQ_DEFAULT_USER=knoxctl -e RABBITMQ_DEFAULT_PASS=KnoxOfflineTest2026 rabbitmq:3.12.2-management
sudo docker exec knoxctl-rabbitmq rabbitmqctl await_startup
```

### Onboard cp

```bash
sudo knoxctl onboard vm cp-node \
  --version=v0.12.7 \
  --vm-mode=systemd \
  --from-source="$PWD/accuknox/v0.12.7" \
  --deploy-rmq=false \
  --rmq-address=127.0.0.1:5672 \
  --auth="$(printf '%s' 'knoxctl:KnoxOfflineTest2026' | base64 | tr -d '\n')" \
  --join-token=825cea79-b9fa-4be0-b9d6-e79e5076ab24 \
  --spire-host=spire.stage.accuknox.com:443 \
  --pps-host=pps.stage.accuknox.com:443 \
  --knox-gateway=knox-gw.stage.accuknox.com:443
```

### Onboard worker

```bash
sudo knoxctl onboard vm node \
  --version=v0.12.7 \
  --vm-mode=systemd \
  --from-source="$PWD/accuknox/v0.12.7" \
  --rmq-address="<CONTROL_PLANE_IP>:5672" \
  --auth="$(printf '%s' 'knoxctl:KnoxOfflineTest2026' | base64 | tr -d '\n')" \
  --cp-node-addr="<CONTROL_PLANE_IP>"
```

### Install scheduled scanner

```bash
sudo knoxctl onboard vm scanner \
  --version=v0.12.7 \
  --vm-mode=systemd \
  --from-source="$PWD/accuknox/v0.12.7" \
  --enable-vmscan \
  --profile=ubuntu20.04 \
  --benchmark=stig \
  --auth-token="<AUTH_TOKEN>" \
  --cluster-name=vm \
  --tenant-id=5 \
  --label="<LABEL>" \
  --url=cspm.stage.accuknox.com \
  --schedule="0 4 * * *"
```

