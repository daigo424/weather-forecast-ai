locals {
  oidc_provider = replace(var.oidc_provider_url, "https://", "")
}

# -------------------------------------------------------
# 1. Argo Workflows IRSA
# -------------------------------------------------------
data "aws_iam_policy_document" "argo_workflows_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider}:sub"
      values   = ["system:serviceaccount:argo:argo-workflows"]
    }
  }
}

resource "aws_iam_role" "argo_workflows" {
  name               = "${var.name_prefix}-argo-workflows-role"
  assume_role_policy = data.aws_iam_policy_document.argo_workflows_assume.json
}

data "aws_iam_policy_document" "argo_workflows_policy" {
  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
      "s3:DeleteObject",
    ]
    resources = [
      var.ml_data_bucket_arn,
      "${var.ml_data_bucket_arn}/*",
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "argo_workflows" {
  name   = "${var.name_prefix}-argo-workflows-policy"
  role   = aws_iam_role.argo_workflows.id
  policy = data.aws_iam_policy_document.argo_workflows_policy.json
}

# -------------------------------------------------------
# 2. MLflow IRSA
# -------------------------------------------------------
data "aws_iam_policy_document" "mlflow_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider}:sub"
      values   = ["system:serviceaccount:mlflow:mlflow"]
    }
  }
}

resource "aws_iam_role" "mlflow" {
  name               = "${var.name_prefix}-mlflow-role"
  assume_role_policy = data.aws_iam_policy_document.mlflow_assume.json
}

data "aws_iam_policy_document" "mlflow_policy" {
  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
      "s3:DeleteObject",
    ]
    resources = [
      var.ml_data_bucket_arn,
      "${var.ml_data_bucket_arn}/*",
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "mlflow" {
  name   = "${var.name_prefix}-mlflow-policy"
  role   = aws_iam_role.mlflow.id
  policy = data.aws_iam_policy_document.mlflow_policy.json
}

# -------------------------------------------------------
# 3. AWS Load Balancer Controller IRSA
# -------------------------------------------------------
data "aws_iam_policy_document" "lbc_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }
  }
}

resource "aws_iam_role" "lbc" {
  name               = "${var.name_prefix}-lbc-role"
  assume_role_policy = data.aws_iam_policy_document.lbc_assume.json
}

resource "aws_iam_policy" "lbc" {
  name   = "${var.name_prefix}-lbc-policy"
  policy = file("${path.module}/policies/aws-lbc-policy.json")
}

resource "aws_iam_role_policy_attachment" "lbc" {
  role       = aws_iam_role.lbc.name
  policy_arn = aws_iam_policy.lbc.arn
}

# -------------------------------------------------------
# 4. weather-api IRSA
# -------------------------------------------------------
data "aws_iam_policy_document" "weather_api_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider}:sub"
      values   = ["system:serviceaccount:weather:weather-api"]
    }
  }
}

resource "aws_iam_role" "weather_api" {
  name               = "${var.name_prefix}-weather-api-role"
  assume_role_policy = data.aws_iam_policy_document.weather_api_assume.json
}

data "aws_iam_policy_document" "weather_api_policy" {
  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      var.ml_data_bucket_arn,
      "${var.ml_data_bucket_arn}/*",
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "kms:Decrypt",
    ]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "weather_api" {
  name   = "${var.name_prefix}-weather-api-policy"
  role   = aws_iam_role.weather_api.id
  policy = data.aws_iam_policy_document.weather_api_policy.json
}
