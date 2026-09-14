locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "iam"
  })
}

# AWS iam capability (T042): least-privilege roles per capability workload.

locals {
  workload_roles = ["catalog", "orchestration", "ingestion", "monitoring"]
}

data "aws_iam_policy_document" "assume_ecs" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "workload" {
  for_each = toset(local.workload_roles)

  name               = "${local.name_prefix}-${each.value}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json

  tags = local.all_tags
}

# Least privilege: workloads may only write audit/metrics logs. Capability
# data-access policies are attached by later features (005 security).
data "aws_iam_policy_document" "logs_minimal" {
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:*:logs:*:*:*"]
  }
}

resource "aws_iam_role_policy" "logs_minimal" {
  for_each = toset(local.workload_roles)

  name   = "logs-minimal"
  role   = aws_iam_role.workload[each.value].id
  policy = data.aws_iam_policy_document.logs_minimal.json
}
