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
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.cluster_job.owner "repoName" .Values.cluster_job.repository "tag" .Values.cluster_job.tag "preserve" .Values.registry.preserveUpstream "image" .Values.cluster_job.image ) }}
{{- end -}}

{{- define "kubescape.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.kubescape.owner "repoName" .Values.kubescape.repository "tag" .Values.kubescape.tag "preserve" .Values.registry.preserveUpstream "image" .Values.kubescape.image ) }}
{{- end -}}

{{/* Construct the URL for jobs */}}
{{- define "global.jobURL" -}}
{{- if and .Values.global.enableJobsUrl .Values.global.agents.url -}}
cspm.{{ .Values.global.agents.url -}}
{{- else -}}
{{- default "" .Values.global.enableJobsUrl -}}
{{- end -}}
{{- end -}}



{{- define "spire.enabled" -}}
  {{- if and (or (ne .Values.global.agents.joinToken "") (ne .Values.global.agents.accessKey "")) (eq .Values.global.authToken "") -}}
    true
  {{- else -}}
    false
  {{- end -}}
{{- end -}}


{{/*
Return full spire host like spire.dev.accuknox.com or localhost
*/}}
{{- define "jobs.spireHost" -}}
{{- if eq (include "spire.enabled" . ) "true" }}spire.{{ .Values.global.agents.url }}{{- else -}}localhost{{- end -}}
{{- end }}



{{/*
Return KnoxGateway URL with port, like knox-gw.dev.accuknox.com:3000 or empty
*/}}
{{- define "jobs.knoxGatewayHost" -}}
{{- if eq (include "spire.enabled" . ) "true" }}knox-gw.{{ .Values.global.agents.url }}:3000{{- else -}}{{""}}{{- end -}}
{{- end }}


{{/*
Return access key URL, like cwpp.dev.accuknox.com/access-token/api/v1/process or empty
*/}}
{{- define "jobs.accessKeyUrl" -}}
{{- if .Values.global.agents.accessKey -}}https://cwpp.{{ .Values.global.agents.url }}/access-token/api/v1/process{{- else -}}{{""}}{{- end -}}
{{- end }}


{{/*
Return cluster name for spire access keys
*/}}
{{- define "jobs.clusterName" -}}
{{- if  ne .Values.global.clusterName "" -}}
    {{- .Values.global.clusterName -}}
{{- else if ne .Values.global.agents.clusterName "" -}}
    {{- .Values.global.agents.clusterName -}}
{{- else -}}
    ""
{{- end -}}
{{- end -}}