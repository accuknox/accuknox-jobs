{{/*
Expand the name of the chart.
*/}}
{{- define "kspm-runtime.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a fullname combining release name and chart name.
*/}}
{{- define "kspm-runtime.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := include "kspm-runtime.name" . }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end -}}

{{/*
Return the chart version.
*/}}
{{- define "kspm-runtime.chart" -}}
{{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/*
Helper to check if Spire roles needs to be enabled.
*/}}
{{- define "spire.roles.enabled" -}}
  {{- if and (or (ne .Values.global.agents.joinToken "") (ne .Values.global.agents.accessKey "")) (eq .Values.global.authToken "") -}}
    true
  {{- else -}}
    false
  {{- end -}}
{{- end -}}

{{/*
Override the agents dependency's endpoint helpers so global.commonPort is
honored even when the dependency's published chart has its own defaults.
*/}}
{{- define "agents.ppsHost" -}}
{{- $rootPps := .Values.global.ppsHost -}}
{{- $enablePps := .Values.global.agents.enablePps | default false -}}
{{- $singleEP := .Values.global.SingleEndpointDeployment | default false -}}
{{- $url := .Values.global.agents.url | default "" -}}
{{- $commonPort := int (.Values.global.commonPort | default 0) -}}
{{- $ppsPort := int (.Values.global.ppsPort | default 443) -}}
{{- $singleEpPort := int (.Values.global.ppsPort | default 8888) -}}
{{- if $commonPort -}}
{{- $ppsPort = $commonPort -}}
{{- $singleEpPort = $commonPort -}}
{{- end -}}
{{- if $rootPps -}}
{{ $rootPps }}
{{- else if and $enablePps $singleEP -}}
{{ printf "%s:%d" $url $singleEpPort }}
{{- else if $enablePps -}}
{{ printf "pps.%s:%d" $url $ppsPort }}
{{- else -}}
{{ printf "localhost:%d" $ppsPort }}
{{- end -}}
{{- end -}}

{{- define "agents.knoxGatewayHost" -}}
{{- $rootGateway := .Values.global.knoxGatewayHost -}}
{{- $enableGateway := .Values.global.agents.enableKnoxGateway -}}
{{- $singleEP := .Values.global.SingleEndpointDeployment | default false -}}
{{- $url := .Values.global.agents.url | default "" -}}
{{- $port := int (.Values.global.knoxGatewayPort | default 3000) -}}
{{- $commonPort := int (.Values.global.commonPort | default 0) -}}
{{- if $commonPort -}}
{{- $port = $commonPort -}}
{{- end -}}
{{- if $rootGateway -}}
{{ $rootGateway }}
{{- else if and $enableGateway $singleEP -}}
{{ printf "%s:%d" $url $port }}
{{- else if $enableGateway -}}
{{ printf "knox-gw.%s:%d" $url $port }}
{{- else -}}
{{ printf "localhost:%d" $port }}
{{- end -}}
{{- end -}}

{{/*
Common labels.
*/}}
{{- define "kspm-runtime.labels" -}}
helm.sh/chart: {{ include "kspm-runtime.chart" . }}
app.kubernetes.io/name: {{ include "kspm-runtime.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
