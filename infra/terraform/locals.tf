locals {
  name_prefix = "${var.project_name}-${var.environment}"

  is_test        = var.environment == "test"
  create_compute = local.is_test && var.compute_enabled

  eks_cluster_name     = try(module.eks[0].cluster_name, "")
  eks_cluster_endpoint = try(module.eks[0].cluster_endpoint, "")
  eks_cluster_ca_cert  = local.create_compute ? base64decode(module.eks[0].cluster_certificate_authority_data) : ""
}
