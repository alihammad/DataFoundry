locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "semantic"
  })
}

# AWS semantic capability — PLACEHOLDER (T049).
# Full semantic-layer behaviour is delivered by feature 006; this module
# implements the common contract with an endpoint-responds health target.

resource "aws_apprunner_service" "semantic" {
  service_name = "${local.name_prefix}-semantic"

  source_configuration {
    auto_deployments_enabled = false

    image_repository {
      image_identifier      = "public.ecr.aws/datafoundry/semantic:0.1.0"
      image_repository_type = "ECR_PUBLIC"
    }
  }

  instance_configuration {
    cpu    = "256"
    memory = "512"
  }

  tags = local.all_tags
}
