module "ml_data" {
  source = "./modules/ml_data"

  name_prefix = local.name_prefix
  github_repo = "daigo424/weather-forecast-ai"
}
