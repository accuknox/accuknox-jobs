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
- name: etc-systemd
  hostPath:
    path: "/etc/systemd"
- name: etc-kubernetes
  hostPath:
    path: "/etc/kubernetes"
{{- if .platform | empty }}
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
{{- else if eq .platform "GKE" }}
- name: home-kubernetes
  hostPath:
    path: "/home/kubernetes"
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
- name: etc-systemd
  mountPath: /etc/systemd
  readOnly: true
- name: etc-kubernetes
  mountPath: /etc/kubernetes
  readOnly: true
{{- if .platform | empty }}
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
- mountPath: /srv/kubernetes/
  name: srv-kubernetes
  readOnly: true
- mountPath: /usr/local/mount-from-host/bin
  name: usr-bin
  readOnly: true
- mountPath: /etc/cni/net.d/
  name: etc-cni-netd
  readOnly: true
- mountPath: /opt/cni/bin/
  name: opt-cni-bin
  readOnly: true
{{- else if eq .platform "GKE" }}
- name: home-kubernetes
  mountPath: /home/kubernetes
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
{{- if not (.targets | empty) }}
- --targets="{{ .targets }}"
{{- end }}
{{- if not (.benchmark | empty) }}
- --benchmark="{{ .benchmark }}"
{{- end }}
{{- if not (.check | empty) }}
- --check="{{ .check }}"
{{- end }}
{{- if not (.skip | empty) }}
- --skip="{{ .skip }}"
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
