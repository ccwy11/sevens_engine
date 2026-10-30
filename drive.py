import os
import json
from pathlib import Path

LOCAL_STORAGE = Path("storage/receipts")
LOCAL_STORAGE.mkdir(parents=True, exist_ok=True)

# Lazy import Google libs so bot starts without them
try:
    from googleapiclient.discovery import build
    from google.oauth2 import service_account
    _HAS_GOOGLE = True
except ImportError:
    _HAS_GOOGLE = False

_credentials = None
_drive_service = None

def _get_service():
    global _credentials, _drive_service
    if _drive_service:
        return _drive_service
    cred_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    if not cred_json or not _HAS_GOOGLE:
        return None
    info = json.loads(cred_json)
    _credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    _drive_service = build("drive", "v3", credentials=_credentials, cache_discovery=False)
    return _drive_service

def upload_file(file_bytes: bytes, filename: str, mime_type: str = "application/pdf") -> str:
    service = _get_service()
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
    if service and folder_id:
        from googleapiclient.http import MediaIoBaseUpload
        import io
        metadata = {"name": filename, "parents": [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
        file = service.files().create(body=metadata, media_body=media, fields="id").execute()
        return file.get("id", "")
    # Local fallback
    local_path = LOCAL_STORAGE / filename
    with open(local_path, "wb") as f:
        f.write(file_bytes)
    return str(local_path)

def download_file(file_id: str) -> bytes:
    service = _get_service()
    if service and not file_id.startswith("storage/"):
        from io import BytesIO
        request = service.files().get_media(fileId=file_id)
        fh = BytesIO()
        downloader = request.execute()
        return downloader
    # Local fallback
    path = Path(file_id)
    if path.exists():
        with open(path, "rb") as f:
            return f.read()
    return b""
