output "endpoint" {
  description = "No endpoint for iam."
  value       = ""
}

output "resource_ids" {
  description = "Service account ids for audit."
  value       = [for sa in google_service_account.workload : sa.id]
}

output "health_target" {
  description = "token-mint probe target."
  value       = google_service_account.workload["catalog"].email
}

output "iam_principal" {
  description = "Service identity created for this capability."
  value       = google_service_account.workload["catalog"].email
}
