locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "catalog"
  })
}

# AWS catalog capability (T045): OpenMetadata containerised (R-04), backed by
# the platform database; http /health target.

resource "aws_ecs_cluster" "catalog" {
  name = "${local.name_prefix}-catalog"
  tags = local.all_tags
}

resource "aws_ecs_task_definition" "openmetadata" {
  family                   = "${local.name_prefix}-openmetadata"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048

  container_definitions = jsonencode([
    {
      name      = "openmetadata"
      image     = "openmetadata/server:1.5.2"
      essential = true
      environment = [
        { name = "OM_ENVIRONMENT", value = var.environment },
        { name = "DB_SCHEME", value = "postgresql" },
      ]
      portMappings = [
        { containerPort = 8585, protocol = "tcp" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.catalog.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "openmetadata"
        }
      }
    },
  ])

  tags = local.all_tags
}

resource "aws_cloudwatch_log_group" "catalog" {
  name              = "/datafoundry/${local.name_prefix}/catalog"
  retention_in_days = 30

  tags = local.all_tags
}

resource "aws_ecs_service" "openmetadata" {
  name            = "${local.name_prefix}-openmetadata"
  cluster         = aws_ecs_cluster.catalog.id
  task_definition = aws_ecs_task_definition.openmetadata.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    assign_public_ip = false
    subnets          = data.aws_subnets.private.ids
  }

  tags = local.all_tags
}

data "aws_subnets" "private" {
  filter {
    name   = "vpc-id"
    values = [var.network_ref]
  }
}
