locals {
  # Glue database 名はハイフン不可のため変換
  glue_db_name = replace(var.name_prefix, "-", "_")
}

resource "aws_glue_catalog_database" "logs" {
  name = "${local.glue_db_name}_logs"
}

resource "aws_glue_catalog_table" "argo_workflow_logs" {
  name          = "argo_workflow_logs"
  database_name = aws_glue_catalog_database.logs.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification" = "json"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.ml_data.bucket}/logs/argo-workflows/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      parameters = {
        # 非 JSON 行（LightGBM の print() 出力など）を NULL として扱い、エラーにしない
        "ignore.malformed.json" = "TRUE"
      }
    }

    columns {
      name = "time"
      type = "string"
    }
    columns {
      name = "level"
      type = "string"
    }
    columns {
      name = "message"
      type = "string"
    }
    columns {
      name = "logger"
      type = "string"
    }
    columns {
      name = "module"
      type = "string"
    }
    columns {
      name = "lineno"
      type = "int"
    }
    columns {
      name = "traceback"
      type = "string"
    }
  }
}

resource "aws_athena_workgroup" "logs" {
  name = "${var.name_prefix}-logs"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = false

    result_configuration {
      output_location = "s3://${aws_s3_bucket.ml_data.bucket}/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
