output "endpoint" {
  description = "OpenMetadata Cloud Run URL."
  value       = google_cloud_run_service.openmetadata.status[0].url
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [google_cloud_run_service.openmetadata.id]
}

output "health_target" {
  description = "http /health probe target."
  value       = "${google_cloud_run_service.openmetadata.status[0].url}/health"
}

output "iam_principal" {
  description = "Catalog service account (from iam capability)."
  value       = google_cloud_run_service.openmetadata.template[0].spec[0].service_account_name
}
