output "endpoint" {
  description = "Composer Airflow URI."
  value       = google_composer_environment.airflow.config[0].airflow_uri
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [google_composer_environment.airflow.id]
}

output "health_target" {
  description = "airflow /health probe target."
  value       = "${google_composer_environment.airflow.config[0].airflow_uri}/health"
}

output "iam_principal" {
  description = "Composer service account (from iam capability)."
  value       = ""
}
