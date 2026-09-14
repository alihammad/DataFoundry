output "endpoint" {
  description = "Bucket logical endpoint."
  value       = "s3://${aws_s3_bucket.platform.bucket}"
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [aws_s3_bucket.platform.arn, aws_dynamodb_table.tf_lock.arn]
}

output "health_target" {
  description = "zone-head probe target (bucket)."
  value       = aws_s3_bucket.platform.bucket
}

output "iam_principal" {
  description = "No service identity for storage."
  value       = ""
}
