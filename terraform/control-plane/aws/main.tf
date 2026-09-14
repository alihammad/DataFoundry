locals {
  all_tags = merge(var.tags, {
    managed_by = "datafoundry"
    component  = "controlplane"
  })
}

# -- KMS (FR-017: metadata store encrypted from creation) -------------------

resource "aws_kms_key" "metadata" {
  description             = "DataFoundry control-plane metadata-store CMK"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = local.all_tags
}

resource "aws_kms_alias" "metadata" {
  name          = "alias/${var.name_prefix}-metadata-cmk"
  target_key_id = aws_kms_key.metadata.key_id
}

# -- Networking --------------------------------------------------------------

resource "aws_vpc" "controlplane" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(local.all_tags, { Name = "${var.name_prefix}-vpc" })
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.controlplane.id
  cidr_block        = cidrsubnet(aws_vpc.controlplane.cidr_block, 8, count.index + 1)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = merge(local.all_tags, { Name = "${var.name_prefix}-private-${count.index}" })
}

resource "aws_security_group" "metadata" {
  name_prefix = "${var.name_prefix}-metadata-"
  description = "Control-plane metadata store (RDS) ingress"
  vpc_id      = aws_vpc.controlplane.id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "PostgreSQL within the VPC"
  }

  tags = local.all_tags
}

# -- Metadata store (RDS PostgreSQL, KMS-encrypted, private) -----------------

resource "aws_db_subnet_group" "metadata" {
  name       = "${var.name_prefix}-metadata-subnet"
  subnet_ids = aws_subnet.private[*].id

  tags = local.all_tags
}

resource "aws_db_instance" "metadata" {
  identifier = "${var.name_prefix}-metadata"

  engine         = "postgres"
  engine_version = "15"
  instance_class = "db.t4g.small"

  allocated_storage = 20
  storage_encrypted = true
  kms_key_id        = aws_kms_key.metadata.arn

  db_name  = "datafoundry"
  username = var.database_username
  manage_master_user_password = true

  publicly_accessible    = false
  db_subnet_group_name   = aws_db_subnet_group.metadata.name
  vpc_security_group_ids = [aws_security_group.metadata.id]

  backup_retention_period = 7
  skip_final_snapshot     = false

  tags = local.all_tags
}

# -- Compute (ECS Fargate) ---------------------------------------------------

resource "aws_ecs_cluster" "controlplane" {
  name = "${var.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.all_tags
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "controlplane_task" {
  name               = "${var.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = local.all_tags
}

resource "aws_cloudwatch_log_group" "controlplane" {
  name              = "/datafoundry/${var.name_prefix}/controlplane"
  retention_in_days = 30

  tags = local.all_tags
}

resource "aws_ecs_task_definition" "controlplane" {
  family                   = "${var.name_prefix}-controlplane"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.controlplane_task.arn
  task_role_arn            = aws_iam_role.controlplane_task.arn

  container_definitions = jsonencode([
    {
      name      = "controlplane"
      image     = var.controlplane_image
      essential = true
      environment = [
        { name = "DF_DATABASE_URL", value = "postgresql+psycopg://${var.database_username}:@${aws_db_instance.metadata.endpoint}/datafoundry" },
        { name = "DF_AUTH_MODE", value = "cloud_iam" },
      ]
      portMappings = [
        { containerPort = 8000, protocol = "tcp" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.controlplane.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "controlplane"
        }
      }
    },
  ])

  tags = local.all_tags
}

# -- TLS endpoint (ALB + HTTPS listener) -------------------------------------

resource "aws_security_group" "alb" {
  name_prefix = "${var.name_prefix}-alb-"
  description = "Control-plane ALB ingress (TLS only)"
  vpc_id      = aws_vpc.controlplane.id

  dynamic "ingress" {
    for_each = var.allowed_cidrs
    content {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "TLS-only ingress (FR-017)"
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.all_tags
}

resource "aws_lb" "controlplane" {
  name               = "${var.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.private[*].id

  tags = local.all_tags
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.controlplane.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.tls_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.controlplane.arn
  }
}

resource "aws_lb_target_group" "controlplane" {
  name        = "${var.name_prefix}-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.controlplane.id
  target_type = "ip"

  health_check {
    path = "/healthz"
  }

  tags = local.all_tags
}

resource "aws_ecs_service" "controlplane" {
  name            = "${var.name_prefix}-service"
  cluster         = aws_ecs_cluster.controlplane.id
  task_definition = aws_ecs_task_definition.controlplane.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.alb.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.controlplane.arn
    container_name   = "controlplane"
    container_port   = 8000
  }

  tags = local.all_tags
}
