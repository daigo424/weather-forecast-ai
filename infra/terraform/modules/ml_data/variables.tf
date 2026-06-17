variable "name_prefix" {
  type        = string
  description = "リソース名のプレフィックス（例: weather-forecast-ai-test）"
}

variable "github_repo" {
  type        = string
  description = "GitHub OIDC 信頼ポリシーに使用するリポジトリ（owner/repo 形式）"
}
