"""
photos.py — every uploaded image goes through here.

The client's content-type and filename are never trusted: the bytes must
decode as a real JPEG/PNG/WEBP, and we store a freshly re-encoded JPEG under
a random name we choose. That means what's on disk is pixels only — no
smuggled HTML/SVG — and no EXIF, so no GPS location of whoever took it.
"""

import asyncio
import io
import re
import uuid

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

import config

MAX_PHOTO_SIZE_BYTES = 4 * 1024 * 1024
ALLOWED_PHOTO_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PHOTO_PIXELS = 40_000_000   # refuse decompression bombs before decoding
MAX_PHOTO_SIDE = 4000
PHOTO_ERROR = "Photo must be a JPEG, PNG, or WEBP image."

# Subfolders of UPLOAD_ROOT, one per kind of evidence.
KINDS = ("complaints", "inspections", "evidence", "compliance")

# Only names we generate are ever served, so paths can't escape the folder.
FILENAME_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|jpeg|png|webp)$")
MEDIA_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def folder(kind):
    path = config.UPLOAD_ROOT / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def reencode(contents: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(contents)) as probe:
            if probe.format not in ALLOWED_PHOTO_FORMATS:
                raise HTTPException(status_code=400, detail=PHOTO_ERROR)
            width, height = probe.size
            if width * height > MAX_PHOTO_PIXELS:
                raise HTTPException(status_code=400, detail="Photo resolution is too large.")
            probe.verify()
        # verify() leaves the image unusable, so decode again for real.
        with Image.open(io.BytesIO(contents)) as img:
            # Apply the EXIF rotation before EXIF is dropped, or phone photos
            # come out sideways.
            img = ImageOps.exif_transpose(img)
            img.thumbnail((MAX_PHOTO_SIDE, MAX_PHOTO_SIDE))
            rgba = img.convert("RGBA")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail=PHOTO_ERROR)

    # A brand-new image, so no metadata from the upload can carry over;
    # transparent areas become white instead of black.
    clean = Image.new("RGB", rgba.size, (255, 255, 255))
    clean.paste(rgba, mask=rgba.getchannel("A"))
    out = io.BytesIO()
    clean.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


async def save_upload(upload: UploadFile, kind: str) -> str:
    """Validates, re-encodes and stores an upload; returns its path."""
    contents = await upload.read(MAX_PHOTO_SIZE_BYTES + 1)
    if len(contents) > MAX_PHOTO_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Photo must be 4MB or smaller.")
    jpeg = await asyncio.to_thread(reencode, contents)
    dest = folder(kind) / f"{uuid.uuid4().hex}.jpg"
    dest.write_bytes(jpeg)
    return str(dest)


def find(filename):
    """(kind, path) for a stored file, or (None, None)."""
    match = FILENAME_RE.match(filename)
    if not match:
        return None, None
    for kind in KINDS:
        path = config.UPLOAD_ROOT / kind / filename
        if path.is_file():
            return kind, path
    return None, None


def media_type(filename):
    return MEDIA_TYPES[FILENAME_RE.match(filename).group(1)]
