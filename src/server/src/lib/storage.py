import hashlib
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
    client.put_object(
        Bucket=BUCKET_NAME.get_secret_value(),
        Key=s3_key,
        Body=file_data,
        ContentType=content_type,
    )

    asset = Asset(
        id=asset_id,
        name=filename,
        size=len(file_data),
        type=content_type,
        hash=file_hash,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
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

    s3_key = _get_s3_key(asset_id)
    client = _get_s3_client()

    try:
        client.delete_object(
            Bucket=BUCKET_NAME.get_secret_value(),
            Key=s3_key,
        )
    except ClientError:
        pass

    db.delete(asset)
    db.commit()
    return True
