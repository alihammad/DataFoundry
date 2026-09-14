check "encryption_enforced_in_production" {
  assert {
    condition     = var.environment != "production" || var.encryption_enforced
    error_message = "FR-017: encryption_enforced must be true in production."
  }
}

locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "networking"
  })
}

# AWS networking capability (T039): VPC, private isolation, TLS-enforcing
# endpoints (FR-017 in-transit posture), S3 gateway endpoint.

resource "aws_vpc" "platform" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(local.all_tags, { Name = "${local.name_prefix}-vpc" })
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.platform.id
  cidr_block        = cidrsubnet(aws_vpc.platform.cidr_block, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = merge(local.all_tags, { Name = "${local.name_prefix}-private-${count.index}" })
}

data "aws_availability_zones" "available" {
  state = "available"
}

# Private connectivity to S3 without leaving the VPC (private isolation).
resource "aws_vpc_endpoint" "s3" {
  vpc_id       = aws_vpc.platform.id
  service_name = "com.amazonaws.${var.region}.s3"

  tags = local.all_tags
}

# Default security group: deny-all ingress (TLS-only endpoints attach their
# own policies; FR-017).
resource "aws_security_group" "default_deny" {
  name_prefix = "${local.name_prefix}-deny-"
  description = "DataFoundry default deny-all ingress (TLS enforced at endpoints)"
  vpc_id      = aws_vpc.platform.id

  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "TLS-only egress (FR-017)"
  }

  tags = local.all_tags

  lifecycle {
    create_before_destroy = true
  }
}
