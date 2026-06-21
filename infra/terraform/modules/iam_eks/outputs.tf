output "ml_workflow_role_arn" {
  value = aws_iam_role.ml_workflow.arn
}

output "mlflow_role_arn" {
  value = aws_iam_role.mlflow.arn
}

output "lbc_role_arn" {
  value = aws_iam_role.lbc.arn
}

output "weather_api_role_arn" {
  value = aws_iam_role.weather_api.arn
}
