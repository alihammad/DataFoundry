output "endpoint" {
  description = "PostgreSQL endpoint (private)."
  value       = aws_db_instance.platform.address
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [aws_db_instance.platform.arn]
}

output "health_target" {
  description = "pg-ping probe target (host:port)."
  value       = "${aws_db_instance.platform.address}:${aws_db_instance.platform.port}"
}

output "iam_principal" {
  description = "No service identity for database."
  value       = ""
}
