output "endpoint" {
  description = "No endpoint for monitoring."
  value       = ""
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [aws_cloudwatch_dashboard.platform.dashboard_arn, aws_cloudwatch_metric_alarm.synthetic.arn]
}

output "health_target" {
  description = "synthetic-datapoint probe target."
  value       = aws_cloudwatch_metric_alarm.synthetic.alarm_name
}

output "iam_principal" {
  description = "No service identity for monitoring."
  value       = ""
}
