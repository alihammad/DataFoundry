output "endpoint" {
  description = "Semantic layer endpoint (placeholder, feature 006)."
  value       = aws_apprunner_service.semantic.service_url
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [aws_apprunner_service.semantic.arn]
}

output "health_target" {
  description = "endpoint-responds probe target."
  value       = "https://${aws_apprunner_service.semantic.service_url}"
}

output "iam_principal" {
  description = "No dedicated service identity."
  value       = ""
}
