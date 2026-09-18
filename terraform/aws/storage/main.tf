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
    capability  = "storage"
  })
}

# AWS storage capability (T041): S3 bucket with Bronze/Silver/Gold prefixes,
# versioned bucket + DynamoDB lock table for Terraform state (R-05), KMS
# encryption from creation (FR-017), Bronze immutability via S3 Object Lock.

resource "aws_s3_bucket" "platform" {
  bucket              = "${local.name_prefix}-${var.region}-data"
  object_lock_enabled = true

  tags = local.all_tags
}

resource "aws_s3_bucket_versioning" "platform" {
  bucket = aws_s3_bucket.platform.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "platform" {
  bucket = aws_s3_bucket.platform.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "platform" {
  bucket = aws_s3_bucket.platform.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_ref
    }
    bucket_key_enabled = true
  }
}

# Bronze zone immutability (constitution Principle III): object lock in
# compliance mode; retention is governed per-object by the medallion feature.
resource "aws_s3_bucket_object_lock_configuration" "platform" {
  bucket = aws_s3_bucket.platform.id

  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = 1
    }
  }
}

# Zone prefix markers (FR-005 — the control-plane init job maintains these).
# quarantine/ added for feature 002 ingestion quarantine routing (US2-AC2).
resource "aws_s3_object" "zone_markers" {
  for_each = toset(["bronze", "silver", "gold", "quarantine"])

  bucket  = aws_s3_bucket.platform.id
  key     = "${each.value}/.datafoundry-keep"
  content = ""

  tags = local.all_tags
}

# Terraform state lock table (R-05: S3 + DynamoDB locking).
resource "aws_dynamodb_table" "tf_lock" {
  name         = "${local.name_prefix}-tflock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_ref
  }

  tags = local.all_tags
}
