import hashlib
import logging
import uuid

import boto3
from botocore.exceptions import ClientError
from fastapi import Depends
from sqlalchemy.orm import Session

from environment import (
    BUCKET_ACCESS_KEY,
    BUCKET_ENDPOINT_URL,
    BUCKET_NAME,
    BUCKET_PREFIX,
    BUCKET_REGION,
    BUCKET_SECRET_KEY,
)
from lib.database import get_database
from lib.models import Asset

_s3_client = None
logger = logging.getLogger(__name__)


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            region_name=BUCKET_REGION.get_secret_value(),
            endpoint_url=BUCKET_ENDPOINT_URL.get_secret_value(),
            aws_access_key_id=BUCKET_ACCESS_KEY.get_secret_value(),
            aws_secret_access_key=BUCKET_SECRET_KEY.get_secret_value(),
        )
    return _s3_client


def _get_s3_key(asset_id: uuid.UUID) -> str:
    prefix = BUCKET_PREFIX.get_secret_value()
    return f"{prefix}/{asset_id}"


def upload_file(file_data: bytes, filename: str, content_type: str, db: Session = Depends(get_database)) -> Asset:
    asset_id = uuid.uuid4()
    file_hash = hashlib.sha256(file_data).hexdigest()
    s3_key = _get_s3_key(asset_id)

    client = _get_s3_client()
    try:
        client.put_object(
            Bucket=BUCKET_NAME.get_secret_value(),
            Key=s3_key,
            Body=file_data,
            ContentType=content_type,
        )
    except ClientError:
        logger.exception(
            "Asset upload failed during S3 put_object",
            extra={"asset_id": str(asset_id), "s3_key": s3_key, "failure_stage": "s3_put_object"},
        )
        raise

    asset = Asset(
        id=asset_id,
        name=filename,
        size=len(file_data),
        type=content_type,
        hash=file_hash,
    )
    try:
        db.add(asset)
        db.commit()
        db.refresh(asset)
    except Exception:
        db.rollback()
        logger.exception(
            "Asset upload failed during DB commit; attempting compensating S3 delete",
            extra={"asset_id": str(asset_id), "s3_key": s3_key, "failure_stage": "db_commit"},
        )
        try:
            client.delete_object(
                Bucket=BUCKET_NAME.get_secret_value(),
                Key=s3_key,
            )
        except ClientError:
            logger.exception(
                "Compensating S3 delete failed after DB commit failure",
                extra={"asset_id": str(asset_id), "s3_key": s3_key, "failure_stage": "s3_compensation_delete"},
            )
        raise
    return asset


def download_file(asset_id: uuid.UUID, db: Session = Depends(get_database)) -> bytes | None:
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        return None

    s3_key = _get_s3_key(asset_id)
    client = _get_s3_client()

    try:
        response = client.get_object(
            Bucket=BUCKET_NAME.get_secret_value(),
            Key=s3_key,
        )
        return response["Body"].read()
    except ClientError:
        return None


def get_file(asset_id: uuid.UUID, db: Session = Depends(get_database)) -> Asset | None:
    return db.query(Asset).filter(Asset.id == asset_id).first()


def delete_file(asset_id: uuid.UUID, db: Session = Depends(get_database)) -> bool:
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        return False

    try:
        db.delete(asset)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Asset delete failed during DB commit",
            extra={"asset_id": str(asset_id), "s3_key": _get_s3_key(asset_id), "failure_stage": "db_commit"},
        )
        raise

    s3_key = _get_s3_key(asset_id)
    client = _get_s3_client()
    try:
        client.delete_object(
            Bucket=BUCKET_NAME.get_secret_value(),
            Key=s3_key,
        )
    except ClientError:
        logger.exception(
            "Asset deleted from DB but S3 delete failed",
            extra={"asset_id": str(asset_id), "s3_key": s3_key, "failure_stage": "s3_delete_post_commit"},
        )
    return True
