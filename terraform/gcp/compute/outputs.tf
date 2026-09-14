output "endpoint" {
  description = "GKE cluster endpoint."
  value       = google_container_cluster.platform.endpoint
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [google_container_cluster.platform.id]
}

output "health_target" {
  description = "instance-ready probe target."
  value       = google_container_cluster.platform.name
}

output "iam_principal" {
  description = "No dedicated service identity (uses iam capability accounts)."
  value       = ""
}
