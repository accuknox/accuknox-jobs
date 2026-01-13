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

{{- define "kubescape.image" -}}
  {{ include "image-name" (dict "url" .Values.global.registry.url "owner" .Values.kubescape.owner "repoName" .Values.kubescape.repository "tag" .Values.kubescape.tag "preserve" .Values.global.registry.preserveUpstream "image" .Values.kubescape.image ) }}
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
  {{- if and (or (ne .Values.global.agents.joinToken "") (ne .Values.global.agents.accessKey "")) (eq .Values.global.authToken "") -}}
    true
  {{- else -}}
    false
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

{{- else if $spireEnabled -}}
{{ printf "knox-gw.%s:%d" $url $port }}

{{- else -}}
{{ "" }}
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
{{- if  ne .Values.global.clusterName "" -}}
    {{- .Values.global.clusterName -}}
{{- else if ne .Values.global.agents.clusterName "" -}}
    {{- .Values.global.agents.clusterName -}}
{{- else -}}
    ""
{{- end -}}
{{- end -}}