"""Upload synthetic deals to the S3 deal store and create demo analyst users.

python -m scripts.seed data            # upload evals/data/deals (never truth.json)
python -m scripts.seed users           # create one user per portfolio/role, prints temp passwords
"""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

import boto3

from scripts.invoke_agent import _cfg

ROOT = Path(__file__).resolve().parents[1]

DEMO_USERS = [
    ("underwriter.cre-west@example.com", "underwriter", "cre-west"),
    ("underwriter.cre-east@example.com", "underwriter", "cre-east"),
    ("underwriter.ag-midwest@example.com", "underwriter", "ag-midwest"),
    ("underwriter.ag-plains@example.com", "underwriter", "ag-plains"),
    ("viewer.cre-west@example.com", "viewer", "cre-west"),
]


def upload_data() -> None:
    bucket = _cfg("DealBucket", "DEAL_BUCKET")
    s3 = boto3.client("s3")
    n = 0
    for path in sorted((ROOT / "evals" / "data" / "deals").rglob("*")):
        if path.is_dir() or path.name == "truth.json" or "work" in path.parts:
            continue
        key = "deals/" + path.relative_to(ROOT / "evals" / "data" / "deals").as_posix()
        s3.upload_file(str(path), bucket, key, ExtraArgs={"ServerSideEncryption": "aws:kms"})
        n += 1
    print(f"uploaded {n} files to s3://{bucket}/deals/ (ground truth excluded)")


def create_users() -> None:
    pool = _cfg("UserPoolId", "UW_USER_POOL_ID")
    idp = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    for email, role, portfolio in DEMO_USERS:
        password = secrets.token_urlsafe(12) + "aA1!"
        try:
            idp.admin_create_user(
                UserPoolId=pool,
                Username=email,
                MessageAction="SUPPRESS",
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "custom:lending_role", "Value": role},
                    {"Name": "custom:portfolio", "Value": portfolio},
                ],
            )
        except idp.exceptions.UsernameExistsException:
            pass
        idp.admin_set_user_password(UserPoolId=pool, Username=email, Password=password, Permanent=True)
        print(f"{email:40s} role={role:12s} portfolio={portfolio:11s} password={password}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["data", "users"])
    {"data": upload_data, "users": create_users}[ap.parse_args().what]()
