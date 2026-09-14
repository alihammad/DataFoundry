output "endpoint" {
  description = "Bucket logical endpoint."
  value       = "gs://${google_storage_bucket.platform.name}"
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [google_storage_bucket.platform.id, google_storage_bucket.bronze.id]
}

output "health_target" {
  description = "zone-head probe target (bucket)."
  value       = google_storage_bucket.platform.name
}

output "iam_principal" {
  description = "No service identity for storage."
  value       = ""
}
