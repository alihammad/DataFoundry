output "endpoint" {
  description = "Semantic layer endpoint (placeholder, feature 006)."
  value       = google_cloud_run_service.semantic.status[0].url
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [google_cloud_run_service.semantic.id]
}

output "health_target" {
  description = "endpoint-responds probe target."
  value       = google_cloud_run_service.semantic.status[0].url
}

output "iam_principal" {
  description = "No dedicated service identity."
  value       = ""
}
