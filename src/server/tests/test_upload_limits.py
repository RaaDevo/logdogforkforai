import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from routes import logs


class DummyDB:
    def add(self, _obj):
        return None

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


class DummyLogFile:
    def __init__(self, **kwargs):
        self.id = "file-1"
        self.asset_id = kwargs["asset_id"]


def test_single_file_too_large(monkeypatch):
    monkeypatch.setattr(logs, "_MAX_UPLOAD_FILE_SIZE_BYTES", 8)
    monkeypatch.setattr(logs, "_MAX_UPLOAD_REQUEST_SIZE_BYTES", 1024)
    upload = UploadFile(file=io.BytesIO(b"0123456789"), filename="big.log", headers=Headers({"content-length": "10"}))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(logs._read_upload_file_limited(upload_file=upload, max_file_size=8, remaining_request_budget=1024))

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail["error"] == "file_too_large"


def test_aggregate_request_too_large(monkeypatch):
    monkeypatch.setattr(logs, "_MAX_UPLOAD_FILE_SIZE_BYTES", 10)
    monkeypatch.setattr(logs, "_MAX_UPLOAD_REQUEST_SIZE_BYTES", 12)

    files = [
        UploadFile(file=io.BytesIO(b"123456"), filename="a.log"),
        UploadFile(file=io.BytesIO(b"1234567"), filename="b.log"),
    ]

    total = 0
    data1, size1 = asyncio.run(logs._read_upload_file_limited(upload_file=files[0], max_file_size=10, remaining_request_budget=12))
    total += size1
    assert len(data1) == 6

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(logs._read_upload_file_limited(upload_file=files[1], max_file_size=10, remaining_request_budget=12 - total))

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail["error"] == "request_too_large"


def test_valid_file_under_limits_processes_normally(monkeypatch):
    monkeypatch.setattr(logs, "_MAX_UPLOAD_FILE_SIZE_BYTES", 64)
    monkeypatch.setattr(logs, "_MAX_UPLOAD_REQUEST_SIZE_BYTES", 128)
    monkeypatch.setattr(logs, "_require_owned_group", lambda **_: SimpleNamespace(id="group-1"))
    monkeypatch.setattr(logs, "LogFile", DummyLogFile)
    monkeypatch.setattr(
        logs,
        "upload_file",
        lambda file_data, filename, content_type, db: SimpleNamespace(id="asset-1", name=filename, size=len(file_data), content_type=content_type),
    )
    monkeypatch.setattr(logs, "_log_file_response", lambda log_file, asset: logs.LogFileResponse(id="f", group_id="g", asset_id=asset.id, name=asset.name, size=asset.size, content_type=asset.content_type, created_at=__import__("datetime").datetime.now(__import__("datetime").UTC)))
    monkeypatch.setattr(logs, "create_process", lambda **_: "proc-1")
    monkeypatch.setattr(logs, "enqueue_process", lambda **_: None)

    response = asyncio.run(logs.upload_log_files(
        group_id="group-1",
        files=[UploadFile(file=io.BytesIO(b"1234"), filename="ok.log")],
        current_user=SimpleNamespace(id="user-1"),
        database=DummyDB(),
    ))

    assert response.status == "queued"
    assert response.process_ids == ["proc-1"]
    assert response.outcomes[0].status == "queued"
