output "endpoint" {
  description = "No endpoint for iam."
  value       = ""
}

output "resource_ids" {
  description = "Role ARNs for audit."
  value       = [for role in aws_iam_role.workload : role.arn]
}

output "health_target" {
  description = "token-mint probe target (first workload role)."
  value       = aws_iam_role.workload["catalog"].name
}

output "iam_principal" {
  description = "Service identity created for this capability."
  value       = aws_iam_role.workload["catalog"].arn
}
