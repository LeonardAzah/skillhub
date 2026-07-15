# storage.py

# --- Cloudinary ---
import cloudinary.uploader

def delete_remote_asset(public_id: str, resource_type: str = "image"):
    cloudinary.uploader.destroy(public_id, resource_type=resource_type)


# --- S3 (boto3) ---
import boto3
from django.conf import settings

_s3_client = boto3.client("s3")

def delete_remote_asset(public_id: str):
    _s3_client.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=public_id)