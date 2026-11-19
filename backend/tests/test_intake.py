import base64
import json
import uuid
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import func, select

from app.config import get_settings
from app.intake import triage_client
from app.main import app
from app.models import (
    Branch,
    BranchAccess,
    IntakeAttempt,
    RequestIntake,
    RequestStatus,
    Role,
    ServiceCategory,
    ServiceRequest,
    User,
)
from app.security import issue_token
from app.triage_types import CATEGORY_IDS

SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "intake_samples.json").read_text())


def auth(user):
    return {"Authorization": f"Bearer {issue_token(user)}"}


def result(**changes):
    return {
        "language_detected": "en",
        "normalized_description": "The pantry faucet is leaking.",
        "original_description": "provider text",
        "category": "plumbing",
        "subcategory": "Faucet leak",
        "priority": "medium",
        "priority_reason": "Local impairment with a workaround.",
        "safety_flags": ["none"],
        "confidence": 0.9,
        "needs_more_info": False,
        "follow_up_questions": [],
        "photo_analysis": {
            "provided": False,
            "visible_issue": None,
            "severity_estimate": "unknown",
            "suggested_tools_or_parts": [],
            "matches_description": None,
        },
        **changes,
    }


def response(data=None, fences=False):
    text = json.dumps(result() if data is None else data)
    if fences:
        text = "```json\n" + text + "\n```"
    return httpx.Response(
        200,
        json={
            "choices": [{"finish_reason": "stop", "message": {"content": text}}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 45},
        },
    )


@pytest.fixture
def intake_people(db, account, monkeypatch):
    monkeypatch.setattr(get_settings(), "groq_api_key", SecretStr("fake-intake-test-key"))
    branch = db.scalar(select(Branch).where(Branch.name == "Branch A"))
    outside = db.scalar(select(Branch).where(Branch.name == "Branch B"))
    users = []
    for name, role, grant in [
        ("manager", Role.branch_manager, branch),
        ("tech", Role.technician, branch),
        ("other", Role.branch_manager, outside),
    ]:
        user = User(
            email=f"intake-{name}@example.com",
            full_name=name,
            role=role,
            password_hash=account.password_hash,
        )
        db.add(user)
        db.flush()
        db.add(BranchAccess(user_id=user.id, branch_id=grant.id))
        users.append(user)
    for category, category_id in CATEGORY_IDS.items():
        db.add(ServiceCategory(id=category_id, name=category.replace("_", " ").title()))
    db.commit()
    return branch, outside, *users


@pytest.fixture
def groq_mock():
    clients = []

    def install(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        app.dependency_overrides[triage_client] = lambda: client

    yield install
    app.dependency_overrides.pop(triage_client, None)
    for client in clients:
        client.close()


def analyze(client, people, **changes):
    branch, _, manager, _, _ = people
    return client.post(
        "/api/requests/triage",
        headers=auth(manager),
        json={
            "description": "The faucet drips after closing.",
            "branch_id": str(branch.id),
            **changes,
        },
    )


def submit(client, people, triage_id=None, **changes):
    branch, _, manager, _, _ = people
    return client.post(
        "/api/requests",
        headers=auth(manager),
        json={
            "branch_id": str(branch.id),
            "title": "Faucet issue",
            "description": "The faucet drips after closing.",
            "location": "Pantry",
            "category_id": "plumbing",
            "priority": "medium",
            "triage_id": triage_id,
            **changes,
        },
    )


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda item: item["name"])
def test_samples_are_valid_and_hazards_and_vagueness_are_enforced(
    client,
    db,
    intake_people,
    groq_mock,
    sample,
):
    vague = sample["name"] == "vague"
    groq_mock(
        lambda _: response(
            result(
                language_detected=sample["language"],
                category=sample["category"],
                confidence=0.4 if vague else 0.9,
                follow_up_questions=["Ano po ang sira?"] if vague else [],
            ),
            fences=True,
        )
    )
    returned = analyze(client, intake_people, description=sample["description"])
    assert returned.status_code == 200, returned.text
    body = returned.json()
    assert body["result"]["original_description"] == sample["description"]
    assert body["result"]["language_detected"] == sample["language"]
    assert db.scalar(select(func.count()).select_from(ServiceRequest)) == 0
    if vague:
        assert body["result"]["needs_more_info"] and body["result"]["follow_up_questions"]
    if sample["name"] == "hazard":
        assert body["result"]["priority"] == "urgent"
        assert "electrical_hazard" in body["result"]["safety_flags"]
    attempt = db.get(IntakeAttempt, uuid.UUID(body["triage_id"]))
    assert (attempt.prompt_tokens, attempt.completion_tokens) == (123, 45)


def test_overrides_snapshots_scoping_and_safety_notifications(
    client, db, account, intake_people, groq_mock
):
    branch, outside, manager, technician, other = intake_people
    text = "may spark sa socket"
    groq_mock(lambda _: response(result(category="electrical")))
    triage = analyze(client, intake_people, description=text).json()
    foreign = client.post(
        "/api/requests",
        headers=auth(other),
        json={
            "branch_id": str(outside.id),
            "title": "Bad reference",
            "location": "Office",
            "description": text,
            "triage_id": triage["triage_id"],
        },
    )
    assert foreign.status_code == 409
    created = submit(
        client,
        intake_people,
        triage["triage_id"],
        description=text,
        category_id="plumbing",
        priority="high",
    )
    assert created.status_code == 201, created.text
    ticket = created.json()
    assert ticket["intake"]["ai_overridden"] is True
    assert ticket["intake"]["ai_priority"] == "urgent"
    assert ticket["intake"]["final_priority"] == "high"
    assert "electrical_hazard" in ticket["safety_flags"]
    assert "ai_raw_response" not in ticket["intake"]
    inbox = client.get("/api/notifications", headers=auth(manager)).json()
    assert any(item["action"] == "safety_flagged" for item in inbox["items"])
    path = f"/api/requests/{ticket['id']}/triage-confirmation"
    confirmation = {"category": "electrical", "priority": "urgent"}
    assert client.patch(path, headers=auth(technician), json=confirmation).status_code == 403
    assert client.patch(path, headers=auth(other), json=confirmation).status_code == 404
    confirmed = client.patch(path, headers=auth(manager), json=confirmation)
    assert confirmed.json()["intake"]["ai_overridden"] is False
    client.patch(
        f"/api/requests/{ticket['id']}/priority", headers=auth(account), json={"priority": "low"}
    )
    assert client.get(f"/api/requests/{ticket['id']}", headers=auth(manager)).json()["intake"][
        "ai_overridden"
    ]
    assert len(client.get("/api/requests?ai_overridden=true", headers=auth(account)).json()) == 1
    assert not client.get("/api/requests?ai_overridden=false", headers=auth(account)).json()
    assert submit(client, intake_people, triage["triage_id"], description=text).status_code == 409
    saved = db.scalar(
        select(RequestIntake).where(RequestIntake.request_id == uuid.UUID(ticket["id"]))
    )
    assert saved.ai_raw_response["category"] == "electrical"
    assert saved.original_description == text


def test_two_round_limit_and_original_text_binding(client, intake_people, groq_mock):
    groq_mock(
        lambda _: response(
            result(confidence=0.2, needs_more_info=True, follow_up_questions=["Ano po ang sira?"])
        )
    )
    text = "sira po"
    initial = analyze(client, intake_people, description=text).json()
    assert submit(client, intake_people, initial["triage_id"], description=text).status_code == 409
    conversation = [{"answers": [{"question": "Ano po ang sira?", "answer": "Aircon po."}]}]
    first = analyze(client, intake_people, description=text, conversation=conversation).json()
    assert "Ano po ang sira?" not in first["result"]["follow_up_questions"]
    conversation.append(
        {"answers": [{"question": "Ano pa ang sintomas?", "answer": "Hindi ko po alam."}]}
    )
    last = analyze(client, intake_people, description=text, conversation=conversation).json()
    assert last["incomplete_info"] and not last["result"]["needs_more_info"]
    assert not last["result"]["follow_up_questions"]
    assert (
        submit(
            client, intake_people, last["triage_id"], description="Different original text"
        ).status_code
        == 409
    )
    ticket = submit(client, intake_people, last["triage_id"], description=text)
    assert ticket.status_code == 201 and ticket.json()["incomplete_info"]
    assert ticket.json()["intake"]["conversation"] == conversation
    assert (
        analyze(client, intake_people, conversation=conversation + conversation).status_code == 422
    )


@pytest.mark.parametrize("failure", ["offline", "invalid_json", "invalid_enum"])
def test_provider_failures_retry_once_and_leave_manual_submission_available(
    client,
    intake_people,
    groq_mock,
    failure,
):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "offline":
            raise httpx.ReadTimeout("secret detail")
        if failure == "invalid_enum":
            return response(result(category="not-a-category"))
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "garbage"}}]}
        )

    groq_mock(handler)
    body = analyze(client, intake_people).json()
    assert body["manual_fallback"] and body["result"] is None and len(calls) == 2
    assert submit(client, intake_people).status_code == 201


def test_disabled_provider_and_per_user_rate_limit(
    client, db, intake_people, groq_mock, monkeypatch
):
    groq_mock(lambda _: pytest.fail("No provider call expected"))
    monkeypatch.setattr(get_settings(), "groq_api_key", None)
    monkeypatch.setattr(get_settings(), "triage_requests_per_minute", 1)
    assert analyze(client, intake_people).json()["manual_fallback"]
    limited = analyze(client, intake_people)
    assert limited.status_code == 429 and limited.headers["Retry-After"] == "60"
    assert submit(client, intake_people).status_code == 201
    assert db.scalar(select(func.count()).select_from(IntakeAttempt)) == 1


def test_photos_are_cleaned_resized_and_only_sent_to_vision_model(client, intake_people, groq_mock):
    branch, _, manager, _, _ = intake_people
    source = Image.new("RGB", (1600, 1200), "white")
    exif = Image.Exif()
    exif[315] = "Private photographer"
    image = BytesIO()
    source.save(image, "JPEG", exif=exif)
    captured = []

    def handler(request):
        payload = json.loads(request.content)
        captured.append(payload)
        assert payload["model"] == get_settings().groq_vision_model
        assert request.extensions["timeout"]["read"] == 15
        contents = payload["messages"][1]["content"]
        decoded = base64.b64decode(contents[1]["image_url"]["url"].split(",", 1)[1])
        with Image.open(BytesIO(decoded)) as clean:
            assert max(clean.size) <= 1024 and not clean.getexif()
        return response(
            result(
                photo_analysis={
                    "provided": True,
                    "visible_issue": "No clear damage visible",
                    "severity_estimate": "unknown",
                    "suggested_tools_or_parts": [],
                    "matches_description": None,
                }
            )
        )

    groq_mock(handler)
    result_ = client.post(
        "/api/requests/triage",
        headers=auth(manager),
        data={
            "description": "Faucet issue",
            "branch_id": str(branch.id),
            "conversation": "[]",
        },
        files={"image": ("issue.jpg", image.getvalue(), "image/jpeg")},
    )
    assert result_.status_code == 200, result_.text
    assert result_.json()["result"]["photo_analysis"]["provided"] is True
    assert len(captured) == 1


@pytest.mark.parametrize(
    "content,mime,status",
    [
        (b"not an image", "image/png", 422),
        (b"x", "image/gif", 422),
        (b"x" * (5 * 1024 * 1024 + 1), "image/jpeg", 413),
    ],
)
def test_invalid_images_do_not_reach_provider(
    client, intake_people, groq_mock, content, mime, status
):
    groq_mock(lambda _: pytest.fail("Invalid images must never reach the provider"))
    returned = client.post(
        "/api/requests/triage",
        headers=auth(intake_people[2]),
        data={"description": "Faucet problem"},
        files={"image": ("issue", content, mime)},
    )
    assert returned.status_code == status, returned.text


def test_access_and_text_privacy(client, intake_people, groq_mock):
    branch, outside, manager, tech, _ = intake_people
    captured = []

    def handler(request):
        text = json.loads(request.content)["messages"][1]["content"]
        captured.append(json.dumps(text))
        assert len(text) == 1  # No vision call without a photo.
        assert "juan@example.com" not in captured[-1] and "+639171234567" not in captured[-1]
        assert "Juan Dela Cruz" not in captured[-1]
        return response()

    groq_mock(handler)
    assert client.post("/api/requests/triage", json={"description": "Hello"}).status_code == 401
    assert (
        client.post(
            "/api/requests/triage", headers=auth(tech), json={"description": "Hello"}
        ).status_code
        == 403
    )
    assert analyze(client, intake_people, branch_id=str(outside.id)).status_code == 403
    text = "Faucet leak. Contact juan@example.com +639171234567. Ako si Juan Dela Cruz"
    body = analyze(client, intake_people, description=text).json()
    assert body["result"]["original_description"] == text
    assert len(captured) == 1


def test_existing_category_edits_sync_provenance_and_closed_intake_can_be_confirmed(
    client,
    db,
    account,
    intake_people,
    groq_mock,
):
    groq_mock(lambda _: response())
    draft = analyze(client, intake_people).json()
    ticket = submit(client, intake_people, draft["triage_id"]).json()
    path = f"/api/requests/{ticket['id']}"
    changed = client.patch(
        f"{path}/category", headers=auth(account), json={"category_id": "electrical"}
    )
    assert changed.status_code == 200
    detail = client.get(path, headers=auth(account)).json()
    assert detail["intake"]["final_category"] == "electrical" and detail["intake"]["ai_overridden"]
    record = db.get(ServiceRequest, uuid.UUID(ticket["id"]))
    record.status = RequestStatus.closed
    db.commit()
    confirmed = client.patch(
        f"{path}/triage-confirmation",
        headers=auth(intake_people[2]),
        json={"category": "plumbing", "priority": "medium"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "closed"
    assert not confirmed.json()["intake"]["ai_overridden"]


def test_missing_model_questions_get_distinct_local_followups(client, intake_people, groq_mock):
    groq_mock(lambda _: response(result(confidence=0.2, follow_up_questions=[])))
    first = analyze(client, intake_people).json()["result"]
    question = first["follow_up_questions"][0]
    second = analyze(
        client,
        intake_people,
        conversation=[
            {
                "answers": [{"question": question, "answer": "No additional details yet."}],
            }
        ],
    ).json()["result"]
    assert second["needs_more_info"] and question not in second["follow_up_questions"]
    exhausted = analyze(
        client,
        intake_people,
        conversation=[
            {
                "answers": [
                    {"question": question, "answer": "Already answered."},
                    {"question": second["follow_up_questions"][0], "answer": "Already answered."},
                ]
            }
        ],
    ).json()
    assert exhausted["manual_fallback"] and exhausted["result"] is None
