import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_db
from app.models import Attachment, RequestStatus, Role, ServiceRequest, User
from app.requests import assigned_work, require_in_progress, visible
from app.security import current_user

router = APIRouter(prefix="/api/requests", tags=["Request photos"])
MAX_BYTES = 8 * 1024 * 1024
MAX_PHOTOS = 20
FORMATS = ("JPEG", "PNG", "WEBP")


def accessible_request(db: Session, user: User, request_id: uuid.UUID, *, lock=False):
    query = visible(user, db).where(ServiceRequest.id == request_id)
    request = db.scalar(query.with_for_update() if lock else query)
    if request is None:
        raise HTTPException(404, "Service request not found")
    return request


def encode(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="JPEG", quality=85)
    return output.getvalue()


def prepare_image(data: bytearray) -> tuple[bytes, bytes]:
    try:
        with Image.open(BytesIO(data), formats=FORMATS) as source:
            if source.width * source.height > 24_000_000 or getattr(source, "is_animated", False):
                raise HTTPException(422, "Choose a still photo up to 24 megapixels")
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail((2400, 2400))
            clean = Image.new("RGB", image.size, "white")
            clean.paste(image, mask=image.getchannel("A"))
            full = encode(clean)
            clean.thumbnail((360, 360))
            return full, encode(clean)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Choose a valid JPEG, PNG, or WebP photo") from exc


@router.post("/{request_id}/photos", status_code=201)
async def upload_photo(
    request_id: uuid.UUID,
    payload: Request,
    name: str = Query(min_length=1, max_length=255),
    work_order_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if user.role not in (Role.branch_manager, Role.technician):
        raise HTTPException(403, "Only branch managers and assigned technicians can add photos")
    data = bytearray()
    async for chunk in payload.stream():
        if len(data) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, "Photos must be 8 MB or smaller")
        data.extend(chunk)
    return await run_in_threadpool(save_photo, db, user, request_id, work_order_id, name, data)


def save_photo(
    db: Session,
    user: User,
    request_id: uuid.UUID,
    work_order_id: uuid.UUID | None,
    name: str,
    data: bytearray,
):
    if user.role == Role.technician:
        if work_order_id is None:
            raise HTTPException(422, "Select an assigned work order")
        request, order = assigned_work(request_id, work_order_id, user, db)
        require_in_progress(request, order)
    else:
        request = accessible_request(db, user, request_id, lock=True)
        if work_order_id is not None:
            raise HTTPException(403, "Only assigned technicians can add repair photos")
        if request.status == RequestStatus.closed:
            raise HTTPException(409, "This request is closed")
    count = db.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.request_id == request_id)
    )
    if count >= MAX_PHOTOS:
        raise HTTPException(409, "This request already has 20 photos")
    full, thumbnail = prepare_image(data)
    photo = Attachment(
        request_id=request_id,
        work_order_id=work_order_id,
        uploaded_by=user.id,
        storage_key=uuid.uuid4().hex,
        original_name=name,
        content_type="image/jpeg",
        image_data=full,
        thumbnail_data=thumbnail,
    )
    db.add(photo)
    db.flush()
    photo_id = photo.id
    db.commit()
    return {"id": photo_id}


@router.get("/{request_id}/photos/{photo_id}")
def view_photo(
    request_id: uuid.UUID,
    photo_id: uuid.UUID,
    thumbnail: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    accessible_request(db, user, request_id)
    column = Attachment.thumbnail_data if thumbnail else Attachment.image_data
    data = db.scalar(
        select(column).where(Attachment.id == photo_id, Attachment.request_id == request_id)
    )
    if data is None:
        raise HTTPException(404, "Photo not found")
    return Response(
        data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
