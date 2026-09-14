output "endpoint" {
  description = "Airflow webserver endpoint (private)."
  value       = aws_mwaa_environment.airflow.webserver_url
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [aws_mwaa_environment.airflow.arn]
}

output "health_target" {
  description = "airflow /health probe target."
  value       = "${aws_mwaa_environment.airflow.webserver_url}/health"
}

output "iam_principal" {
  description = "MWAA execution role."
  value       = aws_iam_role.mwaa.arn
}
