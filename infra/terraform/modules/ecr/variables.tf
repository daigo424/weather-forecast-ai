variable "name_prefix" {
  type = string
}

variable "docker_hub_username" {
  type      = string
  sensitive = true
}

variable "docker_hub_access_token" {
  type      = string
  sensitive = true
}
