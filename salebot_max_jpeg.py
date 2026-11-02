"""SaleBot code_executor helper. No credentials or customer data belong here.

action=inspect: decode the existing OpenAI JPEG and return a small diagnostic.
action=upload: upload it to the exact MAX image-upload URL supplied by SaleBot.
This module does not generate images, store media, or send chat messages.
"""

import base64
import binascii
import hashlib
import json
from urllib.parse import urlsplit

import requests

VERSION = "1.0.0"
MAX_BYTES = 8 * 1024 * 1024


def _result(**values):
    return json.dumps(dict(version=VERSION, **values), ensure_ascii=False)


def handle(data):
    """Return JSON; never echo credentials, signed URLs, or image contents."""
    try:
        params = json.loads(data) if isinstance(data, str) else data
        if not isinstance(params, dict):
            return _result(ok=False, error="invalid_parameters")
        action = params.get("action", "inspect")
        if action not in ("inspect", "upload"):
            return _result(ok=False, error="invalid_action")
        encoded = params.get("image_b64")
        if not isinstance(encoded, str) or not encoded:
            return _result(ok=False, error="missing_image_b64")
        if len(encoded) > ((MAX_BYTES + 2) // 3) * 4:
            return _result(ok=False, error="image_too_large")
        try:
            image = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            return _result(ok=False, error="invalid_base64")
        if not image.startswith(b"\xff\xd8\xff") or not image.endswith(b"\xff\xd9"):
            return _result(ok=False, error="not_jpeg")
        info = dict(byte_length=len(image), sha256=hashlib.sha256(image).hexdigest(),
                    mime_type="image/jpeg")
        if action == "inspect":
            return _result(ok=True, **info)

        upload_url = params.get("upload_url")
        if not isinstance(upload_url, str):
            return _result(ok=False, error="missing_upload_url")
        parts = urlsplit(upload_url)
        if (parts.scheme != "https" or parts.hostname != "iu.oneme.ru"
                or parts.port not in (None, 443) or parts.path != "/uploadImage"
                or parts.username or parts.password or parts.fragment):
            return _result(ok=False, error="invalid_max_upload_url")
        headers = {"Accept": "application/json"}
        token = params.get("max_token")
        if token:
            if not isinstance(token, str) or "\r" in token or "\n" in token:
                return _result(ok=False, error="invalid_authorization")
            headers["Authorization"] = token
        try:
            response = requests.post(upload_url, headers=headers,
                files={"data": ("postcard.jpg", image, "image/jpeg")},
                timeout=(2, 8), allow_redirects=False)
        except requests.exceptions.Timeout:
            return _result(ok=False, error="upload_timeout")
        except requests.exceptions.RequestException:
            return _result(ok=False, error="upload_network_error")
        if not 200 <= response.status_code < 300:
            return _result(ok=False, error="upload_http_error", http_status=response.status_code)
        try:
            body = response.json()
        except ValueError:
            return _result(ok=False, error="upload_invalid_json")
        photos = body.get("photos", {}) if isinstance(body, dict) else {}
        photo_tokens = [entry["token"] for entry in photos.values()
                        if isinstance(entry, dict) and isinstance(entry.get("token"), str)
                        and entry["token"]] if isinstance(photos, dict) else []
        if len(photo_tokens) != 1:
            return _result(ok=False, error="upload_missing_image_token")
        return _result(ok=True, attachment={"type": "image", "payload": {"token": photo_tokens[0]}}, **info)
    except (TypeError, ValueError, KeyError):
        return _result(ok=False, error="invalid_parameters")
    except Exception:
        return _result(ok=False, error="handler_error")
