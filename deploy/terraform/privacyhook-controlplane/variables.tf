variable "name" {
  description = "Helm release name."
  type        = string
  default     = "privacyhook"
}

variable "namespace" {
  description = "Kubernetes namespace to install into."
  type        = string
  default     = "privacyhook"
}

variable "create_namespace" {
  description = "Create the namespace if it does not exist."
  type        = bool
  default     = true
}

variable "chart" {
  description = "Chart location: the published OCI chart by default, or a local path to deploy/helm/privacyhook-controlplane."
  type        = string
  default     = "oci://ghcr.io/adrienchristiaen/charts/privacyhook-controlplane"
}

variable "chart_version" {
  description = "Chart version (null = latest; ignored for a local path)."
  type        = string
  default     = null
}

variable "image_tag" {
  description = "Image tag override (empty = the chart's appVersion)."
  type        = string
  default     = ""
}

variable "team_token" {
  description = "Token developers use with `privacyhook join`. Leave null when using team_token_secret."
  type        = string
  default     = null
  sensitive   = true
}

variable "team_token_secret" {
  description = "Name of an existing Secret (key `token`) holding the team token, e.g. synced from Vault."
  type        = string
  default     = ""
}

variable "postgres_url" {
  description = "postgresql://… URL. Enables multi-replica (HA) mode. Null = SQLite on a PersistentVolume."
  type        = string
  default     = null
  sensitive   = true
}

variable "postgres_secret" {
  description = "Name of an existing Secret (key `url`) holding the Postgres URL, instead of postgres_url."
  type        = string
  default     = ""
}

variable "replica_count" {
  description = "Replicas. More than 1 requires Postgres."
  type        = number
  default     = 1

  validation {
    condition     = var.replica_count >= 1
    error_message = "replica_count must be at least 1."
  }
}

variable "storage_size" {
  description = "PersistentVolume size for SQLite mode."
  type        = string
  default     = "5Gi"
}

variable "storage_class" {
  description = "StorageClass for SQLite mode (empty = cluster default)."
  type        = string
  default     = ""
}

variable "ingress_host" {
  description = "Public hostname for the dashboard and API. Empty = no Ingress."
  type        = string
  default     = ""
}

variable "ingress_class" {
  description = "IngressClass name (e.g. nginx, traefik, alb)."
  type        = string
  default     = ""
}

variable "ingress_annotations" {
  description = "Extra Ingress annotations (cert-manager issuer, ALB settings, …)."
  type        = map(string)
  default     = {}
}

variable "tls_secret_name" {
  description = "TLS Secret for the Ingress host (e.g. created by cert-manager)."
  type        = string
  default     = ""
}

variable "otlp_endpoint" {
  description = "OpenTelemetry collector OTLP/HTTP endpoint, e.g. http://otel-collector.observability:4318."
  type        = string
  default     = ""
}

variable "otlp_headers_secret" {
  description = "Existing Secret (key `headers`) with OTLP headers such as `dd-api-key=…`."
  type        = string
  default     = ""
}

variable "service_monitor" {
  description = "Create a Prometheus Operator ServiceMonitor for /metrics."
  type        = bool
  default     = false
}

variable "policy_rules" {
  description = "Central policy rules pushed to every developer (see controlplane/example-policy.yaml)."
  type = list(object({
    id         = string
    tool       = optional(string, "*")
    match_type = optional(string, "command_regex")
    pattern    = string
    action     = string
    reason     = optional(string, "")
  }))
  default = []
}

variable "extra_values" {
  description = "Additional chart values as YAML, merged last."
  type        = string
  default     = ""
}
