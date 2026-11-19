import json
import uuid

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.ai import ai_client
from app.config import get_settings
from app.main import app
from app.models import (
    Branch,
    BranchAccess,
    MaintenanceLog,
    RequestEvent,
    RequestStatus,
    Role,
    ServiceRequest,
    User,
    WorkOrder,
)
from app.security import issue_token


def auth(user):
    return {"Authorization": f"Bearer {issue_token(user)}"}


def suggestion(**overrides):
    return {
        "summary": "Inspect the faucet and confirm the replacement size.",
        "tasks": ["Inspect the leak", "Replace the confirmed faulty part"],
        "duration_minutes": 120,
        "materials": [
            {"name": "Faucet", "quantity": "1", "unit": "piece", "notes": "Confirm fit first"}
        ],
        "assumptions": ["Water isolation is available"],
        "missing_information": ["Faucet size"],
        **overrides,
    }


def provider_response(data=None, **overrides):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(suggestion() if data is None else data),
                },
            }
        ],
        **overrides,
    }


@pytest.fixture
def ai_case(db, account, monkeypatch):
    monkeypatch.setattr(get_settings(), "groq_api_key", SecretStr("test-key-never-real"))
    branch = db.scalar(select(Branch).where(Branch.name == "Branch A"))
    technician = User(
        email="ai-tech@example.com",
        full_name="Private Technician Name",
        role=Role.technician,
        password_hash=account.password_hash,
    )
    db.add(technician)
    db.flush()
    db.add(BranchAccess(user_id=technician.id, branch_id=branch.id))
    request = ServiceRequest(
        branch_id=branch.id,
        submitted_by=account.id,
        title="Leaking faucet",
        description="The pantry faucet drips.",
        location="Private office location",
    )
    db.add(request)
    db.flush()
    order = WorkOrder(request_id=request.id, technician_id=technician.id, assigned_by=account.id)
    db.add(order)
    db.flush()
    db.add(
        MaintenanceLog(
            work_order_id=order.id,
            recorded_by=technician.id,
            action="Diagnosis",
            notes="Corroded fitting discovered.",
        )
    )
    db.commit()
    return request, order, technician


@pytest.fixture
def provider_mock():
    clients = []

    def install(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        app.dependency_overrides[ai_client] = lambda: client

    yield install
    app.dependency_overrides.pop(ai_client, None)
    for client in clients:
        client.close()


def test_ai_suggestions_are_scoped_structured_and_do_not_change_budgets(
    client,
    db,
    account,
    ai_case,
    provider_mock,
):
    request, order, _ = ai_case
    sent = []

    def handler(outgoing):
        assert str(outgoing.url) == "https://api.groq.com/openai/v1/chat/completions"
        assert outgoing.headers["Authorization"] == "Bearer test-key-never-real"
        payload = json.loads(outgoing.content)
        sent.append(payload)
        assert payload["max_completion_tokens"] == 4096
        assert payload["model"] == get_settings().groq_model
        assert payload["reasoning_effort"] == "low"
        assert "input" not in payload and "instructions" not in payload and "store" not in payload
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert payload["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
        assert payload["messages"][0]["role"] == "system"
        content = payload["messages"][1]["content"]
        context = json.loads(content)
        assert context["maintenance_notes"][0]["notes"] == "Corroded fitting discovered."
        assert "Private Technician Name" not in content
        assert "Private office location" not in content
        assert "@example.com" not in content
        assert "request_id" not in context and "branch_id" not in context
        return httpx.Response(200, json=provider_response())

    provider_mock(handler)
    before = db.scalar(select(func.count()).select_from(RequestEvent))
    result = client.post(f"/api/requests/{request.id}/ai/estimate", headers=auth(account))
    assert result.status_code == 200, result.text
    assert result.json() == suggestion() and len(sent) == 1
    db.refresh(order)
    assert order.price_estimate is None and order.approved_price is None
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == before


def test_ai_requires_admin_branch_access_active_request_and_configuration(
    client,
    db,
    account,
    ai_case,
    provider_mock,
    monkeypatch,
):
    request, _, technician = ai_case
    provider_mock(lambda _: pytest.fail("Provider must not be called"))
    path = f"/api/requests/{request.id}/ai/estimate"
    assert client.post(path).status_code == 401
    assert client.post(path, headers=auth(technician)).status_code == 403
    assert (
        client.post(f"/api/requests/{uuid.uuid4()}/ai/estimate", headers=auth(account)).status_code
        == 404
    )
    monkeypatch.setattr(get_settings(), "groq_api_key", None)
    unconfigured = client.post(path, headers=auth(account))
    assert unconfigured.status_code == 503 and "GROQ_API_KEY" in unconfigured.text
    request.status = RequestStatus.awaiting_verification
    db.commit()
    assert client.post(path, headers=auth(account)).status_code == 409
    request.status = RequestStatus.closed
    db.commit()
    assert client.post(path, headers=auth(account)).status_code == 409
    db.query(BranchAccess).filter(BranchAccess.user_id == account.id).delete()
    db.commit()
    assert client.post(path, headers=auth(account)).status_code == 404


@pytest.mark.parametrize(
    "status,expected", [(401, 503), (403, 503), (429, 503), (500, 502), (400, 502)]
)
def test_ai_provider_errors_do_not_expose_credentials_or_provider_payload(
    client,
    account,
    ai_case,
    provider_mock,
    status,
    expected,
):
    provider_mock(lambda _: httpx.Response(status, json={"error": "SECRET PROVIDER DETAILS"}))
    result = client.post(f"/api/requests/{ai_case[0].id}/ai/estimate", headers=auth(account))
    assert result.status_code == expected
    assert "SECRET" not in result.text and "test-key" not in result.text


@pytest.mark.parametrize(
    "error,expected", [(httpx.ReadTimeout("slow"), 504), (httpx.ConnectError("offline"), 502)]
)
def test_ai_network_failures_allow_manual_estimation(
    client, account, ai_case, provider_mock, error, expected
):
    def fail(_):
        raise error

    provider_mock(fail)
    result = client.post(f"/api/requests/{ai_case[0].id}/ai/estimate", headers=auth(account))
    assert result.status_code == expected


@pytest.mark.parametrize(
    "response",
    [
        provider_response(choices=[{"finish_reason": "length", "message": {"content": "{}"}}]),
        provider_response(
            choices=[{"finish_reason": "stop", "message": {"refusal": "Declined", "content": None}}]
        ),
        provider_response(data=suggestion(duration_minutes=0)),
        provider_response(
            data=suggestion(
                materials=[{"name": "Pipe", "quantity": "0", "unit": "m", "notes": "Check"}]
            )
        ),
        provider_response(
            data=suggestion(
                materials=[
                    {
                        "name": "Pipe",
                        "quantity": "1",
                        "unit": "m",
                        "notes": "Check",
                        "unit_price": "500",
                    }
                ]
            )
        ),
        provider_response(data=suggestion(invented_total="500.00")),
        {"choices": "invalid"},
        {"choices": []},
        provider_response(choices=[{"finish_reason": "stop", "message": {"content": "not json"}}]),
    ],
)
def test_ai_rejects_unusable_or_unpriced_schema_violating_output(
    client, account, ai_case, provider_mock, response
):
    provider_mock(lambda _: httpx.Response(200, json=response))
    result = client.post(f"/api/requests/{ai_case[0].id}/ai/estimate", headers=auth(account))
    assert result.status_code == 502


def test_groq_strict_generation_failure_recovers_once_with_local_validation(
    client,
    db,
    account,
    ai_case,
    provider_mock,
    caplog,
):
    requests = []

    def handler(outgoing):
        requests.append(json.loads(outgoing.content))
        if len(requests) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "json_validate_failed",
                        "message": "SECRET ISSUE DATA",
                        "failed_generation": "SECRET GENERATED DATA",
                    }
                },
            )
        return httpx.Response(200, json=provider_response())

    provider_mock(handler)
    result = client.post(f"/api/requests/{ai_case[0].id}/ai/estimate", headers=auth(account))
    assert result.status_code == 200 and result.json() == suggestion()
    assert len(requests) == 2
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert requests[1]["response_format"] == {"type": "json_object"}
    assert '"additionalProperties": false' in requests[1]["messages"][0]["content"]
    assert requests[0]["messages"][1] == requests[1]["messages"][1]
    assert "SECRET" not in json.dumps(requests) + caplog.text + result.text
    assert "json_validate_failed" in caplog.text
    db.refresh(ai_case[1])
    assert ai_case[1].price_estimate is None and ai_case[1].approved_price is None


@pytest.mark.parametrize(
    "fallback",
    [
        httpx.Response(400, json={"error": {"code": "json_validate_failed"}}),
        httpx.Response(200, json=provider_response(data=suggestion(invented_total="500"))),
    ],
)
def test_groq_fallback_is_bounded_and_never_bypasses_validation(
    client,
    account,
    ai_case,
    provider_mock,
    fallback,
):
    calls = []

    def handler(outgoing):
        calls.append(outgoing)
        return (
            httpx.Response(400, json={"error": {"code": "json_validate_failed"}})
            if len(calls) == 1
            else fallback
        )

    provider_mock(handler)
    result = client.post(f"/api/requests/{ai_case[0].id}/ai/estimate", headers=auth(account))
    assert result.status_code == 502 and len(calls) == 2


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (404, "model_not_found", 503),
        (400, "model_decommissioned", 503),
        (400, "context_length_exceeded", 422),
        (401, "unknown", 503),
        (429, "unknown", 503),
        (400, "unknown", 502),
    ],
)
def test_groq_configuration_and_quota_errors_are_not_retried(
    client,
    account,
    ai_case,
    provider_mock,
    status,
    code,
    expected,
):
    calls = []

    def handler(outgoing):
        calls.append(outgoing)
        return httpx.Response(status, json={"error": {"code": code, "message": "SECRET"}})

    provider_mock(handler)
    result = client.post(f"/api/requests/{ai_case[0].id}/ai/estimate", headers=auth(account))
    assert result.status_code == expected and len(calls) == 1
    assert "SECRET" not in result.text
