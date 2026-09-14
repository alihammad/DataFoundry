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
    capability  = "orchestration"
  })
}

# AWS orchestration capability (T046): MWAA managed Airflow (R-03) behind the
# logical contract; airflow /health target.

resource "aws_s3_bucket" "mwaa_dags" {
  bucket = "${local.name_prefix}-mwaa"

  tags = local.all_tags
}

resource "aws_s3_bucket_versioning" "mwaa_dags" {
  bucket = aws_s3_bucket.mwaa_dags.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "mwaa_dags" {
  bucket = aws_s3_bucket.mwaa_dags.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "assume_mwaa" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["airflow.amazonaws.com", "airflow-env.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "mwaa" {
  name               = "${local.name_prefix}-mwaa-role"
  assume_role_policy = data.aws_iam_policy_document.assume_mwaa.json

  tags = local.all_tags
}

resource "aws_security_group" "mwaa" {
  name_prefix = "${local.name_prefix}-mwaa-"
  description = "MWAA private ingress/egress"
  vpc_id      = var.network_ref

  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }

  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.all_tags

  lifecycle {
    create_before_destroy = true
  }
}

data "aws_subnets" "private" {
  filter {
    name   = "vpc-id"
    values = [var.network_ref]
  }
}

resource "aws_mwaa_environment" "airflow" {
  name               = "${local.name_prefix}-airflow"
  airflow_version    = "2.9.3"
  environment_class  = "mw1.small"
  execution_role_arn = aws_iam_role.mwaa.arn

  source_bucket_arn = aws_s3_bucket.mwaa_dags.arn
  dag_s3_path       = "dags/"

  webserver_access_mode = "PRIVATE_ONLY"

  network_configuration {
    subnet_ids         = slice(data.aws_subnets.private.ids, 0, 2)
    security_group_ids = [aws_security_group.mwaa.id]
  }

  tags = local.all_tags
}
