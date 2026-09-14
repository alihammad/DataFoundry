output "endpoint" {
  description = "Cloud SQL private endpoint."
  value       = google_sql_database_instance.platform.private_ip_address
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [google_sql_database_instance.platform.id]
}

output "health_target" {
  description = "pg-ping probe target (host:5432)."
  value       = "${google_sql_database_instance.platform.private_ip_address}:5432"
}

output "iam_principal" {
  description = "No service identity for database."
  value       = ""
}
