import os
import logging

try:
    import boto3
    from botocore.exceptions import ClientError
    from botocore.client import Config
    HAS_BOTO3 = True
except ImportError:
    boto3 = None
    ClientError = Exception
    Config = None
    HAS_BOTO3 = False

logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "whatsapp-media")

# Initialize boto3 client for MinIO if available
s3_client = None
if HAS_BOTO3:
    try:
        s3_client = boto3.client(
            's3',
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            config=Config(signature_version='s3v4') if Config else None,
            region_name='us-east-1' # dummy region
        )
    except Exception as e:
        logger.warning(f"Could not initialize MinIO S3 client: {e}")

def _ensure_bucket_exists():
    if not s3_client:
        return
    try:
        s3_client.head_bucket(Bucket=MINIO_BUCKET_NAME)
    except Exception as e:
        error_code = getattr(e, 'response', {}).get('Error', {}).get('Code') if hasattr(e, 'response') else None
        if error_code == '404':
            # Create bucket
            logger.info(f"Bucket {MINIO_BUCKET_NAME} does not exist. Creating...")
            s3_client.create_bucket(Bucket=MINIO_BUCKET_NAME)
        else:
            logger.warning(f"MinIO bucket check deferred: {e}")

# Ensure bucket is created on module load if available
try:
    _ensure_bucket_exists()
except Exception as e:
    logger.warning(f"Failed to ensure bucket exists on startup: {e}")

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
