output "argo_workflows_role_arn" {
  value = aws_iam_role.argo_workflows.arn
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
