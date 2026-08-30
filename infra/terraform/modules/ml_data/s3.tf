resource "aws_s3_bucket" "ml_data" {
  bucket        = "${var.name_prefix}-ml-data"
  force_destroy = true
  tags = {
    Name = "${var.name_prefix}-ml-data"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ml_data" {
  bucket = aws_s3_bucket.ml_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "ml_data" {
  bucket                  = aws_s3_bucket.ml_data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "ml_data" {
  # STANDARD: Most expensive; for actively used data with frequent reads and writes.
  # INTELLIGENT_TIERING: Monitors access frequency and automatically moves data to cheaper tiers to reduce costs.
  # GLACIER: For long-term archival (e.g., backups accessed only occasionally).
  # DEEP_ARCHIVE: Lowest-cost storage class AWS offers; retrieval can take up to 12 hours.

  bucket = aws_s3_bucket.ml_data.id

  rule {
    id     = "row-data-lifecycle"
    status = "Enabled"

    filter {
      prefix = "01_row/"
    }

    transition {
      days          = 30
      storage_class = "INTELLIGENT_TIERING"
    }
  }
  rule {
    id     = "processed-data-lifecycle"
    status = "Enabled"

    filter {
      prefix = "02_processed/"
    }

    transition {
      days          = 1095
      storage_class = "GLACIER"
    }
  }
  rule {
    id     = "features-data-lifecycle"
    status = "Enabled"

    filter {
      prefix = "03_features/"
    }

    transition {
      days          = 30
      storage_class = "INTELLIGENT_TIERING"
    }
  }
  dynamic "rule" {
    for_each = toset(["evidently", "mlflow-artifacts"])

    content {
      id     = "${rule.value}-data-lifecycle"
      status = "Enabled"

      filter {
        prefix = "${rule.value}/"
      }

      transition {
        days          = 90
        storage_class = "INTELLIGENT_TIERING"
      }
    }
  }

  rule {
    id     = "argo-workflows-logs-lifecycle"
    status = "Enabled"

    filter {
      prefix = "logs/argo-workflows/"
    }

    expiration {
      days = 30
    }
  }

  rule {
    id     = "athena-results-lifecycle"
    status = "Enabled"

    filter {
      prefix = "athena-results/"
    }

    expiration {
      days = 3
    }
  }
}

# S3 bucket dedicated to storing access logs
resource "aws_s3_bucket" "ml_data_log" {
  bucket = "${var.name_prefix}-ml-data-log"
}

resource "aws_s3_bucket_public_access_block" "ml_data_log" {
  bucket                  = aws_s3_bucket.ml_data_log.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "ml_data_log" {
  bucket = aws_s3_bucket.ml_data_log.id

  rule {
    id     = "delete-old-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }
  }
}

resource "aws_s3_bucket_logging" "ml_data" {
  bucket        = aws_s3_bucket.ml_data.id
  target_bucket = aws_s3_bucket.ml_data_log.id
  target_prefix = "log/"
}
