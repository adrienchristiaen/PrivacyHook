locals {
  scheme  = var.tls_secret_name != "" ? "https" : "http"
  service = "${var.name}${strcontains(var.name, "privacyhook") ? "" : "-privacyhook"}"
}

output "dashboard_url" {
  description = "Team dashboard URL (empty when no ingress_host is set)."
  value       = var.ingress_host != "" ? "${local.scheme}://${var.ingress_host}/" : ""
}

output "service_url" {
  description = "In-cluster URL of the control plane (for CI runners inside the cluster)."
  value       = "http://${local.service}.${var.namespace}.svc.cluster.local:8957"
}

output "join_command" {
  description = "What each developer runs once (token omitted)."
  value       = "privacyhook join ${var.ingress_host != "" ? "${local.scheme}://${var.ingress_host}" : "http://${local.service}.${var.namespace}.svc.cluster.local:8957"} --token <team token>"
}
