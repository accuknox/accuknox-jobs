{{- define "agentsOperator.name" }}
{{- printf "%s" "agents-operator" }}
{{- end }}

{{- define "sharedInformerAgent.name" }}
{{- printf "%s" "shared-informer-agent" }}
{{- end }}

{{- define "policyEnforcementAgent.name" }}
{{- printf "%s" "policy-enforcement-agent" }}
{{- end }}

{{- define "localRegistryAgent.name" }}
{{- printf "%s" "local-registry-agent" }}
{{- end }}


{{- define "feederService.name" }}
{{- printf "%s" "feeder-service" }}
{{- end }}

{{- define "discoveryEngine.name" }}
{{- printf "%s" "discovery-engine" }}
{{- end }}

{{- define "kmux.name" }}
{{- printf "%s" "kmux" }}
{{- end }}

{{- define "cluster.name" -}}
{{- if .Values.agents.clusterName -}}
{{- (printf "%s" (.Values.agents.clusterName| toString)) | quote }}
{{- end -}}
{{- end -}}

{{- define "cluster.id" -}}
{{- if or (.Values.clusterId) (.Values.install.Feeder) -}}
{{- (printf "%s" (.Values.clusterId | toString)) | quote }}
{{- end -}}
{{- end }}

{{- define "tenant.id" -}}
{{- if or (.Values.tenantId) (.Values.install.Feeder) -}}
{{- (printf "%s" (.Values.tenantId | toString)) | quote }}
{{- end -}}
{{- end }}

{{- define "workspace.id" -}}
{{- if or (.Values.workspaceId) (.Values.install.Feeder) -}}
{{- (printf "%s" (.Values.workspaceId | toString)) | quote  }}
{{- end -}}
{{- end }}

{{- define  "onboarding.details" -}}
{{- range list  "CLUSTER_NAME" "cluster_name" "cluster_id" "tenant_id" "workspace_id" }}
- name: {{ . }}
  valueFrom:
    configMapKeyRef:
      name: onboarding-vars
      key: {{ . }}           
{{- end }}
{{- end }}

{{- define  "kubearmor.details" -}} 
{{- range $k, $v := .Values.feederService.kubearmorVars }}
{{- if $v }}
- name: {{ $k }}
  valueFrom:
    configMapKeyRef:
      name: kubearmor-vars
      key: {{ $k }}
{{- else }}
- name: {{$k}}
  value: ""      
{{- end }}      
{{- end }}      
{{- end }}          

{{- define  "splunk.details" -}} 
{{- range $k, $v := .Values.feederService.splunkVars }}
{{- if $v }}
- name: {{ $k }}
  valueFrom:
    configMapKeyRef:
      name: splunk-vars
      key: {{ $k }}
{{- else }}
- name: {{$k}}
  value: ""       
{{- end }}      
{{- end }}      
{{- end }}         

{{- define  "discoveryEngine.details" -}} 
{{- range $k, $v := .Values.feederService.discoveryEngineVars }}
{{- if $v }}
- name: {{ $k }}
  valueFrom:
    configMapKeyRef:
      name: discovery-engine-vars
      key: {{ $k }}
{{- end }}      
{{- end }}      
{{- end }}  


{{- define  "spire.details" -}} 
{{- range $k, $v := .Values.agentsOperator.spireVars }}
{{- if $v }}
- name: {{ $k }}
  valueFrom:
    configMapKeyRef:
      name: spire-vars
      key: {{ $k }}
{{- end }}      
{{- end }}      
{{- end }}  


{{- define "condition-feeder" }}
{{- if eq .Values.install.Feeder false }}
{{- printf "%t" false }}
{{- else }}
{{- if eq .Values.install.Feeder true }}
{{- printf "%t" true }}
{{- else }}
{{- fail "Due to wrong type in .Values.do.*" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "condition-registry-agent" }}
{{- if eq .Values.install.localRegistryAgent false }}
{{- printf "%t" false }}
{{- else }}
{{- if eq .Values.install.localRegistryAgent true }}
{{- printf "%t" true }}
{{- else }}
{{- fail "Due to wrong type in .Values.do.*" }}
{{- end }}
{{- end }}
{{- end }}

{{- define  "azureSentinel.details" -}} 
{{- range $k, $v := .Values.feederService.azureSentinelVars }}
{{- if $v }}
- name: {{ $k }}
  valueFrom:
    configMapKeyRef:
      name: azuresentinel-vars
      key: {{ $k }}
{{- else }}
- name: {{$k}}
  value: ""       
{{- end }}      
{{- end }}
{{- end }}

{{- define  "cilium.details" -}} 
{{- range $k, $v := .Values.feederService.ciliumVars }}
{{- if $v }}
- name: {{ $k }}
  valueFrom:
    configMapKeyRef:
      name: cilium-vars
      key: {{ $k }}
{{- else }}
- name: {{$k}}
  value: ""       
{{- end }}      
{{- end }} 
{{- end }}


{{- define "namespace" }}
{{- .Values.namespace | default $.Release.Namespace }}
{{- end }}

{{- define "cspm-host" }}
{{- if .Values.agents.cspmHost }}
  {{ .Values.agents.cspmHost }}
{{- else }}
  {{ .Values.ppsHost | replace "pps" "cspm" }}
{{- end}}
{{- end}}


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


{{- define "agentsOperator.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.agentsOperator.owner "repoName" .Values.agentsOperator.repository "tag" .Values.agentsOperator.tag "preserve" .Values.registry.preserveUpstream "image" .Values.agentsOperator.image ) }}
{{- end -}}

{{- define "summaryEngine.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.discoveryEngine.owner "repoName" .Values.discoveryEngine.repository "tag" .Values.discoveryEngine.tag "preserve" .Values.registry.preserveUpstream "image" .Values.discoveryEngine.summaryEngine.image  "suffix" "sumengine" )}}
{{- end -}}

{{- define "offloader.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.discoveryEngine.owner "repoName" .Values.discoveryEngine.repository "tag" .Values.discoveryEngine.tag "preserve" .Values.registry.preserveUpstream "image" .Values.discoveryEngine.offloader.image  "suffix" "offloader" )}}
{{- end -}}

{{- define "discover.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.discoveryEngine.owner "repoName" .Values.discoveryEngine.repository "tag" .Values.discoveryEngine.tag "preserve" .Values.registry.preserveUpstream "image" .Values.discoveryEngine.discover.image  "suffix" "discover" )}}
{{- end -}}

{{- define "hardening.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.discoveryEngine.owner "repoName" .Values.discoveryEngine.repository "tag" .Values.discoveryEngine.tag "preserve" .Values.registry.preserveUpstream "image" .Values.discoveryEngine.hardening.image  "suffix" "hardening" )}}
{{- end -}}

{{- define "feeder.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.feederService.owner "repoName" .Values.feederService.repository "tag" .Values.feederService.tag "preserve" .Values.registry.preserveUpstream "image" .Values.feederService.image )}} 
{{- end -}}

{{- define "localRegistryAgent.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.localRegistryAgent.owner "repoName" .Values.localRegistryAgent.repository "tag" .Values.localRegistryAgent.tag "preserve" .Values.registry.preserveUpstream "image" .Values.localRegistryAgent.image )}}
{{- end -}}

{{- define "policyEnforcementAgent.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.policyEnforcementAgent.owner "repoName" .Values.policyEnforcementAgent.repository "tag" .Values.policyEnforcementAgent.tag "preserve" .Values.registry.preserveUpstream "image" .Values.policyEnforcementAgent.image )}}
{{- end -}}

{{- define "sharedInformerAgent.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.sharedInformerAgent.owner "repoName" .Values.sharedInformerAgent.repository "tag" .Values.sharedInformerAgent.tag "preserve" .Values.registry.preserveUpstream "image" .Values.sharedInformerAgent.image )}}
{{- end -}}


{{/*
Return full spire host like spire.dev.accuknox.com or localhost
*/}}
{{- define "agents.spireHost" -}}
{{- if .Values.global.agents.enableSpire -}}spire.{{ .Values.global.agents.url }}{{- else -}}localhost{{- end -}}
{{- end }}


{{/*
Return full pps host like pps.dev.accuknox.com or empty
*/}}
{{- define "agents.ppsHost" -}}
{{- if .Values.global.agents.enablePps -}}pps.{{ .Values.global.agents.url }}{{- else -}}{{""}}{{- end -}}
{{- end }}


{{/*
Return KnoxGateway URL with port, like knox-gw.dev.accuknox.com:3000 or empty
*/}}
{{- define "agents.knoxGatewayHost" -}}
{{- if .Values.global.agents.enableKnoxGateway -}}knox-gw.{{ .Values.global.agents.url }}:3000{{- else -}}{{""}}{{- end -}}
{{- end }}
