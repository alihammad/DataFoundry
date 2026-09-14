output "endpoint" {
  description = "Ingestion Cloud Run URL."
  value       = google_cloud_run_service.ingestion.status[0].url
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [google_cloud_run_service.ingestion.id]
}

output "health_target" {
  description = "endpoint-responds probe target."
  value       = google_cloud_run_service.ingestion.status[0].url
}

output "iam_principal" {
  description = "Ingestion service account (from iam capability)."
  value       = ""
}
