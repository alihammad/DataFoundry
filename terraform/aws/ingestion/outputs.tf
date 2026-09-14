output "endpoint" {
  description = "Ingestion service endpoint."
  value       = aws_apprunner_service.ingestion.service_url
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [aws_apprunner_service.ingestion.arn]
}

output "health_target" {
  description = "endpoint-responds probe target."
  value       = "https://${aws_apprunner_service.ingestion.service_url}"
}

output "iam_principal" {
  description = "App Runner service role (managed)."
  value       = ""
}
