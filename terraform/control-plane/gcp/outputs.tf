output "api_endpoint" {
  description = "HTTPS endpoint of the bootstrapped control plane (Cloud Run)."
  value       = google_cloud_run_service.controlplane.status[0].url
}

output "admin_identity" {
  description = "Admin identity (service account) to grant platform-deploy permissions to."
  value       = google_service_account.controlplane.email
}

output "metadata_endpoint" {
  description = "Metadata-store instance name (Cloud SQL)."
  value       = google_sql_database_instance.metadata.name
}

output "metadata_kms_key_id" {
  description = "Cloud KMS crypto key protecting the metadata store."
  value       = google_kms_crypto_key.metadata.id
}
