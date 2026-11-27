import json

import httpx
import pytest

from app.core.config import Settings
from app.extracta import recovery
from app.extracta.models import DocumentItem, DocumentOrder, DocumentResult, Evidence, Line
from app.extracta.recovery import CallBudget, recover


def sample():
    text = "MERCADORIA 28/10 2 5,00 0,00 1,8 S"
    line = Line(page_number=1, text=text, bbox=(0, 0, 1, 1), strategy="ocr")
    item = DocumentItem(
        line_id="p1-l1",
        page_number=1,
        description="MERCADORIA",
        quantity=2,
        evidence={
            "description": Evidence(page_number=1, text=text, bbox=(0, 0, 1, 1), strategy="ocr")
        },
    )
    result = DocumentResult(
        source_document_id="doc",
        filename="private.pdf",
        sha256="hash",
        profile_id="atacadao_purchase_order",
        orders=[DocumentOrder(items=[item])],
    )
    return result, [line]


def settings(**kwargs):
    return Settings(
        _env_file=None,
        nvidia_api_key="fake-key-for-tests",
        extracta_allow_external_ai=True,
        **kwargs,
    )


def reply(payload, **overrides):
    data = json.loads(payload["messages"][1]["content"])
    target_id = next(
        key for key, target in data["targets"].items() if target["field"] == "unit_price"
    )
    candidate = {
        "target_id": target_id,
        "source_id": data["targets"][target_id]["source_ids"][0],
        "value": "5,00",
        "quote": "5,00",
        **overrides,
    }
    return {
        "choices": [{"message": {"content": json.dumps({"candidates": [candidate]})}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 30},
    }


def test_external_ai_disabled_never_calls_provider(monkeypatch):
    result, lines = sample()

    def forbidden(*args):
        pytest.fail("Não deveria enviar dados externamente")

    monkeypatch.setattr(recovery, "request_json", forbidden)
    recover(result, lines, Settings(_env_file=None, extracta_allow_external_ai=False))
    assert result.llm_calls == 0
    assert not result.recovery_candidates


def test_suggestion_requires_source_and_never_overwrites_local_fields(monkeypatch):
    result, lines = sample()
    recorded = []

    def request(client, config, payload, timeout):
        recorded.append(payload)
        return 200, None, reply(payload)

    monkeypatch.setattr(recovery, "request_json", request)
    recover(result, lines, settings())
    assert result.orders[0].items[0].unit_price is None
    assert result.recovery_candidates[0].normalized_value == "5.00"
    assert result.recovery_candidates[0].page_number == 1
    assert result.llm_calls == 1
    assert result.llm_usage["prompt_tokens"] == 100
    assert "private.pdf" not in json.dumps(recorded)
    assert "fake-key" not in json.dumps(recorded)


def test_fabricated_evidence_is_discarded(monkeypatch):
    result, lines = sample()
    monkeypatch.setattr(
        recovery,
        "request_json",
        lambda client, config, payload, timeout: (
            200,
            None,
            reply(payload, value="900,00", quote="900,00"),
        ),
    )
    recover(result, lines, settings())
    assert not result.recovery_candidates
    assert any("descartado" in event for event in result.recovery_events)


@pytest.mark.parametrize("status", [401, 403, 400])
def test_client_errors_do_not_retry_or_discard_local_result(monkeypatch, status):
    result, lines = sample()
    monkeypatch.setattr(recovery, "request_json", lambda *args: (status, None, None))
    recover(result, lines, settings())
    assert result.llm_calls == 1
    assert result.status == "needs_review"
    assert result.orders[0].items[0].quantity == 2


def test_429_retries_are_charged_against_the_same_budget(monkeypatch):
    result, lines = sample()
    persisted = []
    budget = CallBudget(2, 3, on_reserve=lambda current: persisted.append(current.document_calls))

    def request(*args):
        assert persisted[-1] == len(persisted)
        return 429, "0", None

    monkeypatch.setattr(recovery, "request_json", request)
    recover(result, lines, settings(), budget)
    assert result.llm_calls == 2
    assert persisted == [1, 2]
    assert budget.document_calls == 2


def test_long_retry_after_does_not_retry_early(monkeypatch):
    result, lines = sample()
    monkeypatch.setattr(recovery, "request_json", lambda *args: (429, "120", None))
    recover(result, lines, settings())
    assert result.llm_calls == 1


def test_previously_spent_batch_budget_prevents_any_request(monkeypatch):
    result, lines = sample()
    monkeypatch.setattr(recovery, "request_json", lambda *args: pytest.fail("Limite excedido"))
    recover(result, lines, settings(), CallBudget(3, 9, batch_calls=9))
    assert result.llm_calls == 0


def test_timeout_is_counted_and_does_not_expose_exception_content(monkeypatch):
    result, lines = sample()

    def request(*args):
        raise httpx.ReadTimeout("private-content-and-key")

    monkeypatch.setattr(recovery, "request_json", request)
    monkeypatch.setattr(recovery, "retry_after", lambda _: 0)
    recover(result, lines, settings())
    assert result.llm_calls == 2
    assert "private-content" not in " ".join(result.recovery_events)


def test_cache_is_scoped_to_document_content_profile_and_model(monkeypatch):
    calls = []

    def request(client, config, payload, timeout):
        calls.append(payload)
        return 200, None, reply(payload)

    monkeypatch.setattr(recovery, "request_json", request)
    budget = CallBudget(3, 9)
    result, lines = sample()
    recover(result, lines, settings(), budget)
    repeated, _ = sample()
    recover(repeated, lines, settings(), budget)
    assert len(calls) == 1
    assert repeated.llm_calls == 0
    assert len(repeated.recovery_candidates) == 1
    different, _ = sample()
    different.sha256 = "another-document-hash"
    recover(different, lines, settings(), budget)
    assert len(calls) == 2
    isolated, _ = sample()
    recover(isolated, lines, settings(), CallBudget(3, 9))
    assert len(calls) == 3
    model_changed, _ = sample()
    recover(
        model_changed,
        lines,
        settings(nvidia_model="another-configured-model"),
        CallBudget(3, 9, cache=budget.cache),
    )
    assert len(calls) == 4


def test_http_adapter_rejects_redirects_and_limits_response_size():
    payload = {"model": "test"}
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(307, headers={"location": "https://another.example"})
        ),
        follow_redirects=False,
    ) as client:
        status, _, body = recovery.request_json(client, settings(), payload, 1)
        assert status == 307
        assert body is None
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 262145))
    ) as client:
        with pytest.raises(ValueError, match="limite local"):
            recovery.request_json(client, settings(), payload, 1)
