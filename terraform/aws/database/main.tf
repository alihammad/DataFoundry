locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "database"
  })
}

# AWS database capability (T044): RDS PostgreSQL 15, KMS-encrypted from
# creation (FR-017), private-only (pg-ping health target).

resource "aws_db_instance" "platform" {
  identifier = "${local.name_prefix}-db"

  engine         = "postgres"
  engine_version = "15"
  instance_class = "db.t4g.small"

  allocated_storage = 20
  storage_encrypted = true
  kms_key_id        = var.kms_key_ref

  db_name  = "datafoundry"
  username = "dfadmin"
  # Password comes from Secrets Manager (SC-006: never in config/state
  # plaintext); manage_master_user_password keeps rotation inside RDS+KMS.
  manage_master_user_password = true

  publicly_accessible    = false
  multi_az               = var.environment == "production"
  backup_retention_period = 7
  skip_final_snapshot    = var.environment != "production"

  tags = local.all_tags
}
