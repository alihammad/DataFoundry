output "endpoint" {
  description = "Placeholder endpoint (feature 004)."
  value       = ""
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [google_service_account.quality_runner.id]
}

output "health_target" {
  description = "runner-heartbeat probe target."
  value       = google_service_account.quality_runner.email
}

output "iam_principal" {
  description = "Quality runner service identity."
  value       = google_service_account.quality_runner.email
}
