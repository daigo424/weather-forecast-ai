locals {
  name_prefix = "${var.project_name}-${var.environment}"

  is_test        = var.environment == "test"
  create_compute = local.is_test && var.compute_enabled

  eks_cluster_name = try(module.eks[0].cluster_name, "")

  vpn_cidrs = ["35.75.224.191/32"]
}
