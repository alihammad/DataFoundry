output "endpoint" {
  description = "Placeholder endpoint (feature 004)."
  value       = ""
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [aws_iam_role.quality_runner.arn]
}

output "health_target" {
  description = "runner-heartbeat probe target."
  value       = aws_iam_role.quality_runner.name
}

output "iam_principal" {
  description = "Quality runner service identity."
  value       = aws_iam_role.quality_runner.arn
}
