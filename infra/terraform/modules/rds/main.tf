resource "aws_db_subnet_group" "ml_db" {
  name       = var.name_prefix
  subnet_ids = var.private_subnet_ids

  tags = {
    Name = "${var.name_prefix}-subnet-group"
  }
}

resource "aws_security_group" "ml_db" {
  name        = "${var.name_prefix}-rds-sg"
  description = "Security group for RDS"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  dynamic "ingress" {
    for_each = length(var.allowed_cidrs) > 0 ? [1] : []
    content {
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = var.allowed_cidrs
      description = "Additional access for local development"
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name_prefix}-rds-sg"
  }
}

resource "aws_db_instance" "ml_db" {
  identifier            = var.name_prefix
  engine                = "postgres"
  engine_version        = "16"
  instance_class        = "db.t3.micro"
  allocated_storage     = 20
  max_allocated_storage = 100

  db_name  = "ml_app"
  username = var.db_username
  password = "dummydummydummydummy"

  db_subnet_group_name   = aws_db_subnet_group.ml_db.name
  vpc_security_group_ids = [aws_security_group.ml_db.id]

  multi_az            = false
  publicly_accessible = true
  apply_immediately   = true

  backup_retention_period   = 1
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name_prefix}-final"
  deletion_protection       = false

  tags = {
    Name = var.name_prefix
  }

  lifecycle {
    ignore_changes = [password]
  }
}
