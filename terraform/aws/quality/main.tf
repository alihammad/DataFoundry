locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "quality"
  })
}

# AWS quality capability — PLACEHOLDER (T049).
# Full data-quality-gate behaviour is delivered by feature 004; this module
# implements the common contract with a runner-heartbeat health target.

resource "aws_iam_role" "quality_runner" {
  name = "${local.name_prefix}-quality-runner"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ecs-tasks.amazonaws.com" }
        Action    = "sts:AssumeRole"
      },
    ]
  })

  tags = local.all_tags
}

resource "aws_cloudwatch_log_group" "quality_runner" {
  name              = "/datafoundry/${local.name_prefix}/quality-runner"
  retention_in_days = 30

  tags = local.all_tags
}
