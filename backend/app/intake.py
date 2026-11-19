"""Pre-ticket triage, private provenance, and scoped human confirmation."""

import base64
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.admin import branch_ids
from app.config import get_settings
from app.db import get_db
from app.models import (
    IntakeAttempt,
    Priority,
    RequestEvent,
    RequestIntake,
    Role,
    ServiceCategory,
    ServiceRequest,
    User,
)
from app.photos import prepare_image
from app.requests import visible
from app.security import current_user
from app.triage_prompt import TRIAGE_PROMPT
from app.triage_types import (
    CATEGORY_IDS,
    ConfirmationInput,
    TriageInput,
    TriageResponse,
    TriageResult,
)

router = APIRouter(prefix="/api/requests", tags=["Request intake"])
logger = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def triage_client():
    with httpx.Client(timeout=15) as client:
        yield client


def redact_text(value: str) -> str:
    value = re.sub(r"<[^>]*>", " ", value)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    value = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[email removed]", value)
    value = re.sub(r"(?<!\w)(?:\+?63|0)[\s()-]*9(?:[\s()-]*\d){9}(?!\d)", "[phone removed]", value)
    value = re.sub(
        r"(?i)\b(?:my name is|name:|ako si|pangalan ko ay)\s+[\w.-]+(?:\s+[\w.-]+){0,2}",
        "[name removed]",
        value,
    )
    return value


def safety_flags(text: str) -> list[str]:
    patterns = {
        "electrical_hazard": (
            r"\b(sparks?|sparking|kislap|exposed wir\w*|nakalitaw.{0,15}(kawad|wire))\b"
        ),
        "water_near_electrical": (
            r"(water|tubig|basa).{0,60}(socket|outlet|electri|kuryente)|"
            r"(?:socket|outlet).{0,60}(water|tubig|basa)"
        ),
        "gas_leak": r"gas leak|amoy\s*gas|tagas.{0,15}gas|smell.{0,10}gas",
        "fire_risk": r"\b(sunog|usok|smoke|burning smell)\b",
        "structural_risk": (
            r"gumuho|bumibigay.{0,15}(kisame|pader)|structural damage|falling ceiling"
        ),
        "slip_hazard": r"\b(madulas|slippery|slip hazard)\b",
    }
    return [flag for flag, pattern in patterns.items() if re.search(pattern, text, re.I | re.S)]


def clean_intake_image(data: bytes, content_type: str) -> bytes:
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Intake photos must be 5 MB or smaller")
    if content_type not in IMAGE_TYPES:
        raise HTTPException(422, "Choose a JPEG, PNG, or WebP photo")
    full, _ = prepare_image(bytearray(data))
    # Check the decoded type against the declaration, not the filename.
    with Image.open(BytesIO(data)) as original:
        if original.format != IMAGE_TYPES[content_type]:
            raise HTTPException(422, "The photo contents do not match its file type")
    with Image.open(BytesIO(full)) as source:
        source.thumbnail((1024, 1024))
        output = BytesIO()
        source.save(output, "JPEG", quality=80)
        return output.getvalue()


@router.post("/triage", response_model=TriageResponse)
async def triage(
    payload: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    client: httpx.Client = Depends(triage_client),
):
    if user.role not in (Role.branch_manager, Role.administrator):
        raise HTTPException(403, "Only branch managers and administrators can triage reports")
    # Bound the entire upload before parsing multipart fields or decoding a photo.
    body = bytearray()
    async for chunk in payload.stream():
        if len(body) + len(chunk) > MAX_IMAGE_BYTES + 100_000:
            raise HTTPException(413, "The intake upload is too large")
        body.extend(chunk)
    payload._body = bytes(body)
    image, content_type = None, ""
    try:
        if payload.headers.get("content-type", "").startswith("multipart/form-data"):
            async with payload.form(
                max_files=1, max_fields=4, max_part_size=MAX_IMAGE_BYTES
            ) as form:
                fields = {key: value for key, value in form.items() if key != "image"}
                if "conversation" in fields:
                    fields["conversation"] = json.loads(str(fields["conversation"]))
                uploaded = form.get("image")
                if uploaded is not None:
                    if not isinstance(uploaded, UploadFile):
                        raise ValueError("Invalid image field")
                    content_type = uploaded.content_type or ""
                    image = await uploaded.read(MAX_IMAGE_BYTES + 1)
                data = TriageInput.model_validate(fields)
        else:
            data = TriageInput.model_validate_json(body)
    except (ValueError, ValidationError):
        raise HTTPException(422, "Check the description, branch, and follow-up answers") from None
    return await run_in_threadpool(run_triage, data, image, content_type, user, db, client)


def run_triage(
    data: TriageInput,
    image: bytes | None,
    content_type: str,
    user: User,
    db: Session,
    client: httpx.Client,
):
    grants = branch_ids(db, user.id)
    if not grants or (data.branch_id is not None and data.branch_id not in grants):
        raise HTTPException(403, "You do not have access to this branch")
    image = clean_intake_image(image, content_type) if image is not None else None
    # Serialize reservations per account; failed provider calls also consume a slot.
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    recent = db.scalar(
        select(func.count())
        .select_from(IntakeAttempt)
        .where(
            IntakeAttempt.user_id == user.id,
            IntakeAttempt.created_at >= datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    if recent >= get_settings().triage_requests_per_minute:
        db.rollback()
        raise HTTPException(
            429,
            "AI intake limit reached. Wait a minute or submit manually",
            headers={"Retry-After": "60"},
        )
    attempt = IntakeAttempt(user_id=user.id)
    db.add(attempt)
    db.commit()
    conversation = [round.model_dump() for round in data.conversation]
    all_text = (
        data.description
        + " "
        + " ".join(answer.answer for round in data.conversation for answer in round.answers)
    )
    flags = safety_flags(all_text)
    settings = get_settings()
    if settings.groq_api_key is None or not settings.groq_api_key.get_secret_value().strip():
        return manual_response(
            db,
            attempt,
            flags,
            "AI intake is not configured. Choose category and priority manually.",
        )
    context = {
        "description": redact_text(data.description),
        "location_detail": redact_text(data.location_detail),
        "conversation": [
            {
                "answers": [
                    {"question": redact_text(qa.question), "answer": redact_text(qa.answer)}
                    for qa in round.answers
                ]
            }
            for round in data.conversation
        ],
        "photo_provided": image is not None,
    }
    content = [{"type": "text", "text": json.dumps(context)}]
    if image is not None:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"),
                },
            }
        )
    schema = TriageResult.model_json_schema()
    messages = [
        {"role": "system", "content": TRIAGE_PROMPT + "\nJSON schema:\n" + json.dumps(schema)},
        {"role": "user", "content": content},
    ]
    raw = None
    for _ in range(2):
        try:
            response = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": "Bearer " + settings.groq_api_key.get_secret_value()},
                json={
                    "model": settings.groq_vision_model
                    if image is not None
                    else settings.groq_model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "max_completion_tokens": 2048,
                    "reasoning_effort": "none" if image is not None else "low",
                },
                timeout=15,
            )
            if response.status_code != 200:
                continue
            result = response.json()
            usage = result.get("usage") or {}
            attempt.prompt_tokens += max(0, int(usage.get("prompt_tokens", 0)))
            attempt.completion_tokens += max(0, int(usage.get("completion_tokens", 0)))
            choice = result["choices"][0]
            if choice["finish_reason"] != "stop" or choice["message"].get("refusal"):
                continue
            text = choice["message"]["content"].strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
            parsed = TriageResult.model_validate_json(text)
            raw = parsed.model_dump(mode="json")
            break
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError):
            continue
    if raw is None:
        return manual_response(
            db,
            attempt,
            flags,
            "AI intake is unavailable. You can still submit this issue manually.",
        )
    parsed.original_description = data.description
    if image is None:
        parsed.photo_analysis.provided = False
        parsed.photo_analysis.visible_issue = None
        parsed.photo_analysis.severity_estimate = "unknown"
        parsed.photo_analysis.suggested_tools_or_parts = []
        parsed.photo_analysis.matches_description = None
    else:
        parsed.photo_analysis.provided = True
    flags = list(dict.fromkeys(flags + [flag for flag in parsed.safety_flags if flag != "none"]))
    parsed.safety_flags = flags or ["none"]
    outage = re.search(
        r"walang\s+(kuryente|tubig)|total.{0,15}outage|no power|no water", all_text, re.I
    )
    if flags or outage:
        parsed.priority = "urgent"
        parsed.priority_reason = (
            "Reported safety hazard or critical outage requires immediate review."
        )
    needs = parsed.needs_more_info or parsed.confidence < 0.6
    incomplete = needs and len(data.conversation) == 2
    parsed.needs_more_info = needs and not incomplete
    if not parsed.needs_more_info:
        parsed.follow_up_questions = []
    else:
        asked = {
            qa.question.casefold().strip() for round in data.conversation for qa in round.answers
        }
        parsed.follow_up_questions = [
            q for q in parsed.follow_up_questions if q.casefold().strip() not in asked
        ]
        if not parsed.follow_up_questions:
            options = (
                [
                    "May mahalagang detalye pa po bang hindi nababanggit?",
                    "May iba pa po bang dapat malaman tungkol sa epekto nito sa operasyon?",
                ]
                if parsed.language_detected in ("tl", "taglish")
                else [
                    "What important details about the issue have not yet been covered?",
                    "Is there anything else staff should know about the operational impact?",
                ]
            )
            question = next((q for q in options if q.casefold() not in asked), None)
            if question is None:
                return manual_response(
                    db,
                    attempt,
                    flags,
                    "No new follow-up questions are available. Continue manually.",
                )
            parsed.follow_up_questions = [question]
    snapshot = RequestIntake(
        id=attempt.id,
        user_id=user.id,
        branch_id=data.branch_id,
        original_description=data.description,
        normalized_description=parsed.normalized_description,
        language_detected=parsed.language_detected,
        ai_category=parsed.category,
        ai_subcategory=parsed.subcategory,
        ai_priority=parsed.priority,
        ai_priority_reason=parsed.priority_reason,
        ai_safety_flags=flags,
        ai_confidence=parsed.confidence,
        photo_analysis=parsed.photo_analysis.model_dump(),
        ai_raw_response=raw,
        conversation=conversation,
        incomplete_info=incomplete,
        needs_more_info=parsed.needs_more_info,
    )
    db.add(snapshot)
    attempt.status = "success"
    db.commit()
    log_usage(attempt)
    return TriageResponse(
        result=parsed, triage_id=snapshot.id, incomplete_info=incomplete, safety_flags=flags
    )


def log_usage(attempt: IntakeAttempt):
    logger.info(
        "Intake %s status=%s prompt_tokens=%d completion_tokens=%d",
        attempt.id,
        attempt.status,
        attempt.prompt_tokens,
        attempt.completion_tokens,
    )


def manual_response(db, attempt, flags, message):
    attempt.status = "manual"
    db.commit()
    log_usage(attempt)
    return TriageResponse(
        result=None, triage_id=None, manual_fallback=True, message=message, safety_flags=flags
    )


def sync_confirmation(request: ServiceRequest, db: Session):
    intake = db.scalar(select(RequestIntake).where(RequestIntake.request_id == request.id))
    if intake is None:
        return
    reverse = {value: key for key, value in CATEGORY_IDS.items()}
    intake.final_category = reverse.get(request.category_id, request.category_id)
    intake.final_priority = request.priority
    intake.ai_overridden = intake.ai_category is not None and (
        intake.final_category != intake.ai_category or intake.final_priority != intake.ai_priority
    )


def attach_intake(request: ServiceRequest, data, user: User, db: Session):
    if data.triage_id is not None:
        snapshot = db.scalar(
            select(RequestIntake)
            .where(
                RequestIntake.id == data.triage_id,
                RequestIntake.user_id == user.id,
            )
            .with_for_update()
        )
        if snapshot is None or snapshot.request_id is not None:
            raise HTTPException(409, "This intake is unavailable. Analyze again or submit manually")
        if snapshot.original_description != data.description or snapshot.branch_id not in (
            None,
            data.branch_id,
        ):
            raise HTTPException(
                409, "The issue or branch changed. Analyze again or submit manually"
            )
        if snapshot.needs_more_info:
            raise HTTPException(
                409, "Answer the follow-up questions before submitting, or choose manual intake"
            )
        snapshot.request_id = request.id
        snapshot.branch_id = request.branch_id
    else:
        snapshot = RequestIntake(
            user_id=user.id,
            branch_id=request.branch_id,
            request_id=request.id,
            original_description=data.description,
            normalized_description=request.description,
            language_detected="other",
            ai_safety_flags=safety_flags(data.description),
        )
        db.add(snapshot)
    db.flush()
    sync_confirmation(request, db)
    if snapshot.ai_safety_flags:
        db.add(
            RequestEvent(
                request_id=request.id,
                actor_id=user.id,
                action="safety_flagged",
                details={"safety_flags": snapshot.ai_safety_flags},
            )
        )


def intake_output(request: ServiceRequest, db: Session):
    intake = db.scalar(select(RequestIntake).where(RequestIntake.request_id == request.id))
    if intake is None:
        return None
    return {
        field: getattr(intake, field)
        for field in (
            "original_description",
            "normalized_description",
            "language_detected",
            "ai_category",
            "ai_subcategory",
            "ai_priority",
            "ai_priority_reason",
            "ai_safety_flags",
            "ai_confidence",
            "photo_analysis",
            "final_category",
            "final_priority",
            "ai_overridden",
            "incomplete_info",
            "conversation",
        )
    }


@router.patch("/{request_id}/triage-confirmation")
def confirm_intake(
    request_id: uuid.UUID,
    data: ConfirmationInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if user.role not in (Role.branch_manager, Role.administrator):
        raise HTTPException(403, "Only branch managers and administrators can confirm intake")
    request = db.scalar(visible(user, db).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(404, "Service request not found")
    category_id = CATEGORY_IDS[data.category]
    if db.get(ServiceCategory, category_id) is None:
        raise HTTPException(422, "The intake categories are unavailable. Apply migrations first")
    previous = {"category_id": request.category_id, "priority": request.priority}
    request.category_id, request.priority = category_id, Priority(data.priority)
    if previous != {"category_id": category_id, "priority": data.priority}:
        sync_confirmation(request, db)
        db.add(
            RequestEvent(
                request_id=request.id,
                actor_id=user.id,
                action="intake_confirmed",
                details={
                    "previous": previous,
                    "category": data.category,
                    "priority": data.priority,
                },
            )
        )
    db.commit()
    from app.requests import output

    return output(request, db)
