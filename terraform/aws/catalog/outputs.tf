output "endpoint" {
  description = "OpenMetadata logical endpoint."
  value       = "http://${aws_ecs_service.openmetadata.name}.internal"
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [aws_ecs_cluster.catalog.arn, aws_ecs_service.openmetadata.id]
}

output "health_target" {
  description = "http /health probe target."
  value       = "http://${aws_ecs_service.openmetadata.name}.internal/health"
}

output "iam_principal" {
  description = "No dedicated service identity (uses iam capability roles)."
  value       = ""
}
