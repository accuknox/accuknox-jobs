{{/*
Expand the name of the chart.
*/}}
{{- define "cis-k8s-job.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "cis-k8s-job.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "cis-k8s-job.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "cis-k8s-job.labels" -}}
helm.sh/chart: {{ include "cis-k8s-job.chart" . }}
{{ include "cis-k8s-job.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "cis-k8s-job.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cis-k8s-job.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "cis-k8s-job.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "cis-k8s-job.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "volumes" }}
- name: datapath
  emptyDir: {}
- name: var-lib-kubelet
  hostPath:
    path: "/var/lib/kubelet"
{{- if not $.Values.global.talosEnv }}
- name: etc-systemd
  hostPath:
    path: "/etc/systemd"
{{- end }}
- name: etc-kubernetes
  hostPath:
    path: "/etc/kubernetes"
{{- if eq .platform "GKE" }}
# Use emptyDir for paths that are read-only on GKE
- name: home-kubernetes
  emptyDir: {}
- name: srv-kubernetes
  emptyDir: {}
- name: opt-cni-bin
  emptyDir: {}
- name: etc-cni-netd
  emptyDir: {}
- name: usr-bin
  emptyDir: {}
{{- else if .platform | empty }}
- name: var-lib-cni
  hostPath:
    path: /var/lib/cni
- hostPath:
    path: /var/lib/etcd
  name: var-lib-etcd
- hostPath:
    path: /var/lib/kube-scheduler
  name: var-lib-kube-scheduler
- hostPath:
    path: /var/lib/kube-controller-manager
  name: var-lib-kube-controller-manager
- hostPath:
    path: /lib/systemd
  name: lib-systemd
- hostPath:
    path: /srv/kubernetes
  name: srv-kubernetes
- hostPath:
    path: /usr/bin
  name: usr-bin
- hostPath:
    path: /etc/cni/net.d/
  name: etc-cni-netd
- hostPath:
    path: /opt/cni/bin/
  name: opt-cni-bin
{{- else if eq .platform "AKS" }}
- name: etc-default
  hostPath:
    path: "/etc/default"
{{- end }}
{{- end }}

{{- define "volumeMounts" }}
- mountPath: /data
  name: datapath
- name: var-lib-kubelet
  mountPath: /var/lib/kubelet
  readOnly: true
{{- if not $.Values.global.talosEnv }}
- name: etc-systemd
  mountPath: /etc/systemd
  readOnly: true
{{- end }}
- name: etc-kubernetes
  mountPath: /etc/kubernetes
  readOnly: true
{{- if eq .platform "GKE" }}
- name: home-kubernetes
  mountPath: /home/kubernetes
  readOnly: true
- name: srv-kubernetes
  mountPath: /srv/kubernetes
  readOnly: false
- name: opt-cni-bin
  mountPath: /opt/cni/bin
  readOnly: false
- name: etc-cni-netd
  mountPath: /etc/cni/net.d
  readOnly: false
- name: usr-bin
  mountPath: /usr/local/mount-from-host/bin
  readOnly: false
{{- else if .platform | empty }}
- name: var-lib-cni
  mountPath: /var/lib/cni
  readOnly: true
- mountPath: /var/lib/etcd
  name: var-lib-etcd
  readOnly: true
- mountPath: /var/lib/kube-scheduler
  name: var-lib-kube-scheduler
  readOnly: true
- mountPath: /var/lib/kube-controller-manager
  name: var-lib-kube-controller-manager
  readOnly: true
- mountPath: /lib/systemd/
  name: lib-systemd
  readOnly: true
{{- else if eq .platform "AKS" }}
- name: etc-default
  mountPath: /etc/default
  readOnly: true
{{- end }}
{{- end }}

{{- define "cmd" }}
- kube-bench
- run
- --json
- --outputfile=/data/report.json
{{- if not (.benchmark | empty) }}
- --config-dir
- /opt/kube-bench/cfg
- --benchmark
- {{ .benchmark }}
{{- else }}
- --config-dir
- /opt/kube-bench/cfg
- --benchmark
- cis-1.11
{{- if not (.platform | empty) }}
- --config-dir
- /opt/kube-bench/cfg
{{- if eq .platform "GKE" }}
- --benchmark
- gke-1.8.0
{{- else if eq .platform "AKS" }}
- --benchmark
- aks-1.7
{{- else if eq .platform "EKS" }}
- --benchmark
- eks-1.7.0
{{- end }}
{{- end }}
{{- end }}
{{- if not (.targets | empty) }}
- --targets
- {{ .targets }}
{{- end }}
{{- if not (.check | empty) }}
- --check
- {{ .check }}
{{- end }}
{{- if not (.skip | empty) }}
- --skip
- {{ .skip }}
{{- end }}
{{- end }}

{{- define "masterConfig" }}
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: node-role.kubernetes.io/control-plane
              operator: Exists
        - matchExpressions:
            - key: node-role.kubernetes.io/master
              operator: Exists
tolerations:
  - key: node-role.kubernetes.io/master
    operator: Exists
    effect: NoSchedule
  - key: node-role.kubernetes.io/control-plane
    operator: Exists
    effect: NoSchedule
{{- end }}


{{- define "image-name" -}}

  {{- $image := .image -}}
  {{- $url := .url -}}
  {{- $owner := .owner -}}
  {{- $repoName := .repoName -}}
  {{- $tag := .tag -}}
  {{- $preserve := .preserve -}}
  {{- $suffix := .suffix -}}

  {{- if $image -}}
    {{- $image -}}
  {{- else -}}

    {{- $parts := list -}}

    {{- if $url -}}
      {{- $parts = append $parts $url -}}
    {{- end -}}

    {{- if $preserve -}}
	    {{- if $owner -}}
	      {{- $parts = append $parts $owner -}}
	    {{- end -}}
	  {{- end -}}

    {{- if $repoName -}}
      {{- if $suffix -}}
        {{- $repoName = printf "%s-%s" $repoName $suffix -}}
      {{- end -}}
      {{- $parts = append $parts $repoName -}}
    {{- end -}}

    {{- $imageName := join "/" $parts -}}

    {{- if $tag -}}
      {{- printf "%s:%s" $imageName $tag -}}
    {{- else -}}
      {{- $imageName -}}
    {{- end -}}

  {{- end -}}

{{- end -}}


{{- define "cluster_job.image" -}}
  {{ include "image-name" (dict "url" .Values.global.registry.url "owner" .Values.cluster_job.owner "repoName" .Values.cluster_job.repository "tag" .Values.cluster_job.tag "preserve" .Values.global.registry.preserveUpstream "image" .Values.cluster_job.image ) }}
{{- end -}}

{{- define "kubeBench.image" -}}
  {{ include "image-name" (dict "url" .Values.global.registry.url "owner" .Values.kubeBench.owner "repoName" .Values.kubeBench.repository "tag" .Values.kubeBench.tag "preserve" .Values.global.registry.preserveUpstream "image" .Values.kubeBench.image ) }}
{{- end -}}


{{- define "global.jobURL" -}}
{{- $root := .Top | default . -}}
{{- $enableJobs := $root.Values.global.enableJobsUrl | default false -}}
{{- $url := $root.Values.global.agents.url | default "" -}}
{{- $singleEP := $root.Values.global.SingleEndpointDeployment | default false -}}

{{- if and $enableJobs $root.Values.global.cspmHost -}}
{{ $root.Values.global.cspmHost }}

{{- else if and $enableJobs $url $singleEP -}}
{{ printf "%s" $url }}:{{ $root.Values.global.cspmPort | default 443 }}

{{- else if and $enableJobs $url -}}
cspm.{{ $url }}

{{- else -}}
{{ "" }}

{{- end -}}
{{- end }}


{{- define "spire.enabled" -}}
  {{- if or .Values.global.agents.enabled .Values.global.inClusterScan.enabled -}}
    false
  {{- else -}}
    true
  {{- end -}}
{{- end -}}


{{/*
Return full spire host:
0. If global spireHost set → use it
1. If spire enabled AND SingleEndpointDeployment enabled → <url>
2. If spire enabled → spire.<url>
3. If SingleEndpointDeployment enabled → <url>
4. Else → localhost
*/}}

{{- define "jobs.spireHost" -}}
{{- $root := .Top | default . -}}
{{- $spireHost := $root.Values.global.spireHost | default "" -}}
{{- $spireEnabled := $root.Values.global.agents.enableSpire | default false -}}
{{- $singleEP := $root.Values.global.SingleEndpointDeployment | default false -}}
{{- $url := $root.Values.global.agents.url | default "" -}}

{{- if $spireHost -}}
{{ $spireHost }}

{{- else if and $spireEnabled $singleEP -}}
{{ $url }}

{{- else if $spireEnabled -}}
{{ printf "spire.%s" $url }}

{{- else if $singleEP -}}
{{ $url }}

{{- else -}}
localhost

{{- end -}}
{{- end }}




{{/*
Return KnoxGateway URL with port:
1. If spire enabled AND SingleEndpointDeployment enabled → <url>:<port>
2. If ONLY SingleEndpointDeployment enabled → <url>:<port>
3. If spire enabled only → knox-gw.<url>:<port>
4. Else → ""
*/}}
{{- define "jobs.knoxGatewayHost" -}}
{{- $root := .Top | default . -}}
{{- $spireEnabled := eq (include "spire.enabled" $root) "true" -}}
{{- $singleEP := $root.Values.global.SingleEndpointDeployment | default false -}}
{{- $url := $root.Values.global.agents.url | default "" -}}
{{- $port := int ($root.Values.global.knoxGatewayPort | default 3000) -}}

{{- if and $spireEnabled $singleEP -}}
{{ printf "%s:%d" $url $port }}

{{- else if and (not $spireEnabled) $singleEP -}}
{{ printf "%s:%d" $url $port }}

{{- else -}}
{{ printf "knox-gw.%s:%d" $url $port }}
{{- end }}
{{- end }}


{{/*
Return access key URL:
1. If accessKey exists AND SingleEndpointDeployment enabled → <url>/access-token/api/v1/process
2. If accessKey exists only → https://cwpp.<url>/access-token/api/v1/process
3. Else → ""
*/}}
{{- define "jobs.accessKeyUrl" -}}
{{- $root := .Top | default . -}}
{{- $accessKey := $root.Values.global.agents.accessKey | default "" -}}
{{- $singleEP := $root.Values.global.SingleEndpointDeployment | default false -}}
{{- $url := $root.Values.global.agents.url | default "" -}}

{{- if and $accessKey $singleEP -}}
{{ printf "%s/access-token/api/v1/process" $url }}

{{- else if $accessKey -}}
{{ printf "https://cwpp.%s/access-token/api/v1/process" $url }}

{{- else -}}
{{ "" }}
{{- end }}
{{- end }}



{{/*
Return cluster name for spire access keys
*/}}
{{- define "jobs.clusterName" -}}
{{- coalesce .Values.global.clusterName .Values.global.agents.clusterName -}}
{{- end -}}


{{- define "spire.agent" -}}
  {{- if eq .Values.global.agents.enabled true -}}
    {{- printf "agents-operator.%s.svc.cluster.local:9091" .Release.Namespace -}}
  {{- else if eq .Values.global.inClusterScan.enabled true -}}
    {{- printf "kubeshield-spire-agent.%s.svc.cluster.local:9091" .Release.Namespace -}}
  {{- else -}}
    "localhost:9091"
  {{- end -}}
{{- end -}}