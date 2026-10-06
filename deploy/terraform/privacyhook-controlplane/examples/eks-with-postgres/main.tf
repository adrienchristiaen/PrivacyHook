# Example: Kubernetes cluster already configured, Postgres for HA, nginx ingress
# with cert-manager TLS, events forwarded to the platform's OTel collector.

provider "helm" {
  kubernetes {
    config_path = "~/.kube/config"
  }
}

variable "team_token" {
  type      = string
  sensitive = true
}

variable "postgres_url" {
  type      = string
  sensitive = true
}

module "privacyhook" {
  source = "../.."

  team_token    = var.team_token
  postgres_url  = var.postgres_url
  replica_count = 2

  ingress_host        = "privacyhook.acme.internal"
  ingress_class       = "nginx"
  ingress_annotations = { "cert-manager.io/cluster-issuer" = "letsencrypt" }
  tls_secret_name     = "privacyhook-tls"

  otlp_endpoint   = "http://otel-collector.observability:4318"
  service_monitor = true

  policy_rules = [{
    id      = "no-prod-deploy-from-laptop"
    tool    = "Bash"
    pattern = "deploy.*--env[= ]prod"
    action  = "warn"
    reason  = "prod deploys go through CI"
  }]
}

output "join_command" {
  value = module.privacyhook.join_command
}
