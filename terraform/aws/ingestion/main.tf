locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "ingestion"
  })
}

# AWS ingestion capability (T047): ingestion service runtime (App Runner),
# endpoint-responds health target.

resource "aws_apprunner_service" "ingestion" {
  service_name = "${local.name_prefix}-ingestion"

  source_configuration {
    auto_deployments_enabled = false

    image_repository {
      image_identifier      = "public.ecr.aws/datafoundry/ingestion:0.1.0"
      image_repository_type = "ECR_PUBLIC"
    }
  }

  instance_configuration {
    cpu    = "256"
    memory = "512"
  }

  network_configuration {
    egress_configuration {
      egress_type = "VPC"
    }
  }

  tags = local.all_tags
}
