# AWS CLI で最新の手動スナップショット ARN を取得する
# スナップショットが存在しない場合は {"arn": ""} を返す（エラーにならない）
data "external" "latest_snapshot" {
  program = ["bash", "-c", <<-EOT
    ARN=$(aws rds describe-db-snapshots \
      --db-instance-identifier "${var.name_prefix}" \
      --snapshot-type manual \
      --query 'sort_by(DBSnapshots, &SnapshotCreateTime)[-1].DBSnapshotArn' \
      --output text 2>/dev/null)
    if [ -z "$ARN" ] || [ "$ARN" = "None" ]; then
      printf '{"arn": ""}'
    else
      printf '{"arn": "%s"}' "$ARN"
    fi
  EOT
  ]
}

locals {
  latest_snapshot_arn = data.external.latest_snapshot.result["arn"] != "" ? data.external.latest_snapshot.result["arn"] : null
}

# DB 削除時に同名の既存 final snapshot を削除して新しいスナップショットを作れるようにする
resource "terraform_data" "snapshot_cleanup" {
  input = "${var.name_prefix}-final"

  provisioner "local-exec" {
    when    = destroy
    command = "aws rds delete-db-snapshot --db-snapshot-identifier ${self.output} 2>/dev/null || true"
  }

  depends_on = [aws_db_instance.ml_db]
}

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

  snapshot_identifier = local.latest_snapshot_arn # スナップショット未存在時は null → 新規作成

  tags = {
    Name = var.name_prefix
  }

  lifecycle {
    ignore_changes = [password, snapshot_identifier]
  }
}
