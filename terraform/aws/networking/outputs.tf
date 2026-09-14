# Common outputs (capability-catalog.md) + network_ref extra for wiring.

output "endpoint" {
  description = "Logical endpoint (none for networking)."
  value       = ""
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [aws_vpc.platform.arn, aws_security_group.default_deny.arn]
}

output "health_target" {
  description = "dns-resolve probe target."
  value       = aws_vpc.platform.id
}

output "iam_principal" {
  description = "No service identity for networking."
  value       = ""
}

output "network_ref" {
  description = "VPC id consumed by dependent capability modules."
  value       = aws_vpc.platform.id
}
