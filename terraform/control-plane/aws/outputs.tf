output "api_endpoint" {
  description = "HTTPS endpoint of the bootstrapped control plane."
  value       = "https://${aws_lb.controlplane.dns_name}"
}

output "admin_identity" {
  description = "Admin identity (task role ARN) to grant platform-deploy permissions to."
  value       = aws_iam_role.controlplane_task.arn
}

output "metadata_endpoint" {
  description = "Metadata-store endpoint (RDS)."
  value       = aws_db_instance.metadata.endpoint
}

output "metadata_kms_key_arn" {
  description = "KMS key ARN protecting the metadata store."
  value       = aws_kms_key.metadata.arn
}
