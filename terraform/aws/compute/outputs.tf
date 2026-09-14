output "endpoint" {
  description = "ECS cluster logical endpoint."
  value       = ""
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [aws_ecs_cluster.platform.arn]
}

output "health_target" {
  description = "instance-ready probe target."
  value       = aws_ecs_cluster.platform.name
}

output "iam_principal" {
  description = "No dedicated service identity (uses iam capability roles)."
  value       = ""
}
