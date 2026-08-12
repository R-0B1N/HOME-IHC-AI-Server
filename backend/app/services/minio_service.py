import os
import boto3
from botocore.exceptions import ClientError
from botocore.client import Config
import logging

logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "whatsapp-media")

# Initialize boto3 client for MinIO
s3_client = boto3.client(
    's3',
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
    config=Config(signature_version='s3v4'),
    region_name='us-east-1' # dummy region
)

def _ensure_bucket_exists():
    try:
        s3_client.head_bucket(Bucket=MINIO_BUCKET_NAME)
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code')
        if error_code == '404':
            # Create bucket
            logger.info(f"Bucket {MINIO_BUCKET_NAME} does not exist. Creating...")
            s3_client.create_bucket(Bucket=MINIO_BUCKET_NAME)
            # Make it private by default (which it is)
        else:
            logger.error(f"Error checking/creating bucket {MINIO_BUCKET_NAME}: {e}")

# Ensure bucket is created on module load
try:
    _ensure_bucket_exists()
except Exception as e:
    logger.error(f"Failed to ensure bucket exists on startup: {e}")

def upload_media(file_data: bytes, object_name: str, content_type: str = "application/octet-stream") -> str:
    """
    Uploads media to MinIO and returns a pre-signed URL valid for 1 hour.
    """
    try:
        s3_client.put_object(
            Bucket=MINIO_BUCKET_NAME,
            Key=object_name,
            Body=file_data,
            ContentType=content_type
        )
        logger.info(f"Successfully uploaded {object_name} to MinIO")
        return generate_presigned_url(object_name)
    except ClientError as e:
        logger.error(f"Failed to upload media to MinIO: {e}")
        return ""

def generate_presigned_url(object_name: str, expires_in: int = 3600) -> str:
    """
    Generates a pre-signed URL for temporary access to a private object.
    """
    try:
        response = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': MINIO_BUCKET_NAME, 'Key': object_name},
            ExpiresIn=expires_in
        )
        return response
    except ClientError as e:
        logger.error(f"Failed to generate presigned URL for {object_name}: {e}")
        return ""
