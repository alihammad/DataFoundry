output "endpoint" {
  description = "No endpoint for monitoring."
  value       = ""
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [google_monitoring_alert_policy.synthetic.id]
}

output "health_target" {
  description = "synthetic-datapoint probe target."
  value       = google_monitoring_alert_policy.synthetic.name
}

output "iam_principal" {
  description = "No service identity for monitoring."
  value       = ""
}
