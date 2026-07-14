module "ml_data" {
  source = "./modules/ml_data"

  name_prefix = local.name_prefix
  github_repo = "daigo424/weather-forecast-ai"
}


module "network" {
  count = local.is_test ? 1 : 0

  source           = "./modules/network"
  name_prefix      = local.name_prefix
  vpc_cidr         = var.vpc_cidr
  azs              = ["ap-northeast-1a", "ap-northeast-1c"]
  create_nat       = var.compute_enabled
  create_endpoints = var.compute_enabled
}

module "ecr" {
  count = local.is_test ? 1 : 0

  source                  = "./modules/ecr"
  name_prefix             = local.name_prefix
  docker_hub_username     = var.docker_hub_username
  docker_hub_access_token = var.docker_hub_access_token

  services = ["api", "frontend", "ml-workflow", "mlflow"]
}

module "bastion" {
  count = local.create_compute ? 1 : 0

  source           = "./modules/bastion"
  name_prefix      = local.name_prefix
  vpc_id           = module.network[0].vpc_id
  public_subnet_id = module.network[0].public_subnet_ids[0]
}

module "rds" {
  count = local.is_test ? 1 : 0

  source             = "./modules/rds"
  name_prefix        = local.name_prefix
  vpc_id             = module.network[0].vpc_id
  vpc_cidr           = module.network[0].vpc_cidr
  private_subnet_ids = module.network[0].private_subnet_ids
  allowed_cidrs      = local.vpn_cidrs
}

module "eks" {
  count = local.create_compute ? 1 : 0

  source             = "./modules/eks"
  name_prefix        = local.name_prefix
  eks_version        = var.eks_version
  private_subnet_ids = module.network[0].private_subnet_ids
}

module "iam_eks" {
  count = local.create_compute ? 1 : 0

  source             = "./modules/iam_eks"
  name_prefix        = local.name_prefix
  oidc_provider_arn  = module.eks[0].oidc_provider_arn
  oidc_provider_url  = module.eks[0].oidc_provider_url
  ml_data_bucket_arn = module.ml_data.bucket_arn
  kms_key_arn        = module.ml_data.kms_key_arn
}
