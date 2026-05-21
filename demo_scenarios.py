"""Fixed DriftGuard demo scenarios shared by the CLI mock and Lambda demo API."""

from __future__ import annotations

from typing import Any, Dict


S3_PUBLIC_ACCESS_HCL = """terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

variable "bucket_name" {
  description = "Name of the drifted S3 bucket to lock down."
  type        = string
  default     = "example-public-assets"
}

resource "aws_s3_bucket_public_access_block" "driftguard" {
  bucket = var.bucket_name

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
"""


SECURITY_GROUP_HCL = """terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

variable "vpc_id" {
  description = "VPC that owns the drifted administrative security group."
  type        = string
  default     = "vpc-0123456789abcdef0"
}

variable "approved_admin_cidr" {
  description = "Approved administrative access range."
  type        = string
  default     = "203.0.113.10/32"
}

resource "aws_security_group" "app_admin" {
  name        = "app-admin"
  description = "Administrative access restricted by DriftGuard remediation."
  vpc_id      = var.vpc_id

  ingress {
    description = "SSH from approved admin network"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.approved_admin_cidr]
  }

  tags = {
    ManagedBy = "Terraform"
  }
}
"""


RDS_INSTANCE_CLASS_HCL = """terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

variable "db_identifier" {
  description = "Name of the drifted RDS instance."
  type        = string
  default     = "orders-prod"
}

variable "db_password" {
  description = "Existing application database password."
  type        = string
  sensitive   = true
}

resource "aws_db_instance" "orders" {
  identifier                = var.db_identifier
  allocated_storage         = 100
  engine                    = "postgres"
  engine_version            = "15.5"
  instance_class            = "db.t3.medium"
  username                  = "app_user"
  password                  = var.db_password
  apply_immediately         = false
  backup_retention_period   = 7
  deletion_protection       = true
  final_snapshot_identifier = "${var.db_identifier}-driftguard-final"
  publicly_accessible       = false
  storage_encrypted         = true
}
"""


DEMO_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "s3": {
        "label": "S3 drift",
        "title": "S3 public access drift",
        "description": (
            "A bucket's public access controls changed outside Terraform, creating "
            "a clear data exposure risk."
        ),
        "issue_description": (
            "S3 bucket example-public-assets drifted from Terraform and now allows "
            "public access. Remediate by enforcing S3 public access blocking in Terraform."
        ),
        "aws_event": {
            "source": "aws.s3",
            "detail-type": "DriftGuard Demo Drift Event",
            "account": "123456789012",
            "region": "us-east-1",
            "resources": ["arn:aws:s3:::example-public-assets"],
            "detail": {
                "resource_type": "aws_s3_bucket_public_access_block",
                "resource_id": "example-public-assets",
                "drift_type": "public_access_enabled",
                "expected": {
                    "block_public_acls": True,
                    "block_public_policy": True,
                    "ignore_public_acls": True,
                    "restrict_public_buckets": True,
                },
                "actual": {
                    "block_public_acls": False,
                    "block_public_policy": False,
                    "ignore_public_acls": False,
                    "restrict_public_buckets": False,
                },
            },
        },
        "triage_category": "security",
        "severity": "high",
        "triage_reason": (
            "The drift appears to expose an AWS storage resource publicly and should "
            "be remediated through Terraform."
        ),
        "impact_summary": (
            "- **Security risk:** Public access drift can expose sensitive data or "
            "create an unintended internet-facing attack surface.\n"
            "- **Estimated monthly cost impact:** Usually low direct cloud spend, "
            "but high incident/compliance exposure if abused or discovered in audit.\n"
            "- **Operational impact:** Creates manual remediation work and weakens "
            "confidence that Terraform reflects production."
        ),
        "reason_for_fix": (
            "Adds an explicit S3 public access block so Terraform enforces private "
            "bucket posture and reviewers can approve the remediation."
        ),
        "terraform_hcl": S3_PUBLIC_ACCESS_HCL,
    },
    "security-group": {
        "label": "Network drift",
        "title": "Security group exposure drift",
        "description": (
            "An administrative security group was opened to the internet outside "
            "the approved Terraform review path."
        ),
        "issue_description": (
            "Security group sg-0baddrift drifted from Terraform and now allows SSH "
            "from 0.0.0.0/0. Remediate by restricting SSH to the approved admin CIDR."
        ),
        "aws_event": {
            "source": "aws.ec2",
            "detail-type": "DriftGuard Demo Drift Event",
            "account": "123456789012",
            "region": "us-east-1",
            "resources": [
                "arn:aws:ec2:us-east-1:123456789012:security-group/sg-0baddrift"
            ],
            "detail": {
                "resource_type": "aws_security_group",
                "resource_id": "sg-0baddrift",
                "drift_type": "public_ssh_ingress",
                "expected": {
                    "protocol": "tcp",
                    "from_port": 22,
                    "to_port": 22,
                    "cidr_ipv4": "203.0.113.10/32",
                },
                "actual": {
                    "protocol": "tcp",
                    "from_port": 22,
                    "to_port": 22,
                    "cidr_ipv4": "0.0.0.0/0",
                },
            },
        },
        "triage_category": "security",
        "severity": "critical",
        "triage_reason": (
            "The drift opens administrative access to the internet and should be "
            "corrected before it becomes a persistent exposure."
        ),
        "impact_summary": (
            "- **Security risk:** Public SSH increases brute-force, credential "
            "stuffing, and remote access exposure.\n"
            "- **Estimated monthly cost impact:** Direct monthly cost is usually "
            "low, but incident response and audit exposure can be severe.\n"
            "- **Operational impact:** The change bypassed Terraform review, so "
            "reviewers need clear evidence of the intended network boundary."
        ),
        "reason_for_fix": (
            "Replaces public SSH exposure with an approved administrative CIDR so "
            "the intended network boundary is reviewable in Terraform."
        ),
        "terraform_hcl": SECURITY_GROUP_HCL,
    },
    "rds": {
        "label": "Cost drift",
        "title": "RDS instance class drift",
        "description": (
            "A database instance was resized outside Terraform, creating cost drift "
            "and an unclear rollback path."
        ),
        "issue_description": (
            "RDS instance orders-prod drifted from Terraform. Terraform expects "
            "db.t3.medium, but AWS now shows db.r6i.2xlarge. Remediate by restoring "
            "the approved instance class in Terraform."
        ),
        "aws_event": {
            "source": "aws.rds",
            "detail-type": "DriftGuard Demo Drift Event",
            "account": "123456789012",
            "region": "us-east-1",
            "resources": ["arn:aws:rds:us-east-1:123456789012:db:orders-prod"],
            "detail": {
                "resource_type": "aws_db_instance",
                "resource_id": "orders-prod",
                "drift_type": "instance_class_changed",
                "expected": {
                    "instance_class": "db.t3.medium",
                    "publicly_accessible": False,
                    "storage_encrypted": True,
                },
                "actual": {
                    "instance_class": "db.r6i.2xlarge",
                    "publicly_accessible": False,
                    "storage_encrypted": True,
                },
            },
        },
        "triage_category": "cost",
        "severity": "medium",
        "triage_reason": (
            "The drift changes database capacity outside Terraform and should be "
            "reviewed before the larger class becomes the new normal."
        ),
        "impact_summary": (
            "- **Security risk:** The drift does not directly expose the database, "
            "but unmanaged configuration changes weaken review and rollback control.\n"
            "- **Estimated monthly cost impact:** A larger RDS class can add hundreds "
            "of dollars per month depending on region, storage, and reservation coverage.\n"
            "- **Operational impact:** Because the change happened outside Terraform, "
            "rollback ownership and approval context are unclear."
        ),
        "reason_for_fix": (
            "Restores the approved RDS instance class in Terraform so cost drift is "
            "visible, reviewable, and reversible through the normal infrastructure workflow."
        ),
        "terraform_hcl": RDS_INSTANCE_CLASS_HCL,
    },
}


def detect_demo_scenario(text: str) -> str:
    """Infer one of the fixed demo scenarios from prompt text."""

    normalized = text.lower()
    if "rds" in normalized or "db.r6i" in normalized or "orders-prod" in normalized:
        return "rds"
    if "security group" in normalized or "0.0.0.0/0" in normalized or "ssh" in normalized:
        return "security-group"
    return "s3"


def get_demo_scenario(key: str) -> Dict[str, Any]:
    """Return a fixed scenario or raise a predictable KeyError."""

    return DEMO_SCENARIOS[key]
