"""会话与版本管理测试，不调用真实模型或地图。"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.models.schemas import HousingDecisionRequest

from app.repositories.conversation_repository import (
    ConversationConflictError,
    ConversationRepository,
)


def test_create_and_reopen(
    tmp_path,
    housing_request,
):
    db_path = tmp_path / "conversation.sqlite3"

    repository = ConversationRepository(db_path)

    created = repository.create(housing_request)

    reopened = ConversationRepository(db_path)
    loaded = reopened.get(created.id)

    assert loaded.current_version == 1
    assert loaded.current.version == 1
    assert loaded.current.history_id is None

    assert loaded.current.request.model_dump() == (
        housing_request.model_dump()
    )


def test_new_version_keeps_old_request(
    tmp_path,
    housing_request,
):
    repository = ConversationRepository(
        tmp_path / "conversation.sqlite3"
    )

    created = repository.create(housing_request)

    data = housing_request.model_dump()
    data["monthly_budget"] = 6000

    next_request = HousingDecisionRequest.model_validate(
        data
    )

    updated = repository.create_version(
        session_id=created.id,
        expected_version=1,
        request=next_request,
    )

    assert updated.current_version == 2
    assert updated.current.request.monthly_budget == 6000
    assert updated.current.history_id is None

    versions = repository.list_versions(created.id)

    assert [item.version for item in versions] == [2, 1]
    assert versions[1].request.monthly_budget == 5000


def test_stale_version_is_rejected(
    tmp_path,
    housing_request,
):
    repository = ConversationRepository(
        tmp_path / "conversation.sqlite3"
    )

    created = repository.create(housing_request)

    repository.create_version(
        created.id,
        expected_version=1,
        request=housing_request,
    )

    with pytest.raises(ConversationConflictError):
        repository.create_version(
            created.id,
            expected_version=1,
            request=housing_request,
        )

    assert repository.get(
        created.id
    ).current_version == 2


def test_two_concurrent_changes_only_one_succeeds(
    tmp_path,
    housing_request,
):
    db_path = tmp_path / "conversation.sqlite3"
    repository = ConversationRepository(db_path)

    created = repository.create(housing_request)

    def update(budget: int) -> str:
        data = housing_request.model_dump()
        data["monthly_budget"] = budget

        request = HousingDecisionRequest.model_validate(
            data
        )

        # 各线程创建自己的仓库对象和数据库连接。
        worker_repository = ConversationRepository(
            db_path
        )

        try:
            worker_repository.create_version(
                created.id,
                expected_version=1,
                request=request,
            )
            return "success"

        except ConversationConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, [6000, 7000]))

    assert sorted(results) == [
        "conflict",
        "success",
    ]

    current = repository.get(created.id)

    assert current.current_version == 2
    assert current.current.request.monthly_budget in (
        6000,
        7000,
    )

    assert len(
        repository.list_versions(created.id)
    ) == 2


def test_conversation_api(
    client,
    valid_payload,
):
    created_response = client.post(
        "/api/conversations",
        json={"request": valid_payload},
    )

    assert created_response.status_code == 201

    session_id = created_response.json()["id"]

    loaded = client.get(
        f"/api/conversations/{session_id}"
    )

    assert loaded.status_code == 200
    assert loaded.json()["current_version"] == 1

    changed = {
        **valid_payload,
        "monthly_budget": 6000,
    }

    updated = client.post(
        f"/api/conversations/{session_id}/versions",
        json={
            "expected_version": 1,
            "request": changed,
        },
    )

    assert updated.status_code == 201
    assert updated.json()["current_version"] == 2

    stale = client.post(
        f"/api/conversations/{session_id}/versions",
        json={
            "expected_version": 1,
            "request": valid_payload,
        },
    )

    assert stale.status_code == 409


def test_invalid_budget_does_not_change_version(
    client,
    valid_payload,
):
    created = client.post(
        "/api/conversations",
        json={"request": valid_payload},
    )

    session_id = created.json()["id"]

    invalid = {
        **valid_payload,
        "monthly_budget": 100,
    }

    response = client.post(
        f"/api/conversations/{session_id}/versions",
        json={
            "expected_version": 1,
            "request": invalid,
        },
    )

    assert response.status_code == 422

    loaded = client.get(
        f"/api/conversations/{session_id}"
    )

    assert loaded.json()["current_version"] == 1

def prepare_history(
    history_repository,
    housing_request,
):
    from app.core.config import Settings

    from tests.test_housing_orchestrator import (
        make_demo_orchestrator,
    )

    orchestrator = make_demo_orchestrator(None)

    orchestrator.settings = Settings(
        _env_file=None,
        workflow_budget_seconds=600,
    )

    result = orchestrator.run(housing_request)

    return history_repository.save(
        request=housing_request,
        result=result,
    )


def test_bind_matching_history(
    client,
    valid_payload,
    housing_request,
    history_repository,
):
    history_id = prepare_history(
        history_repository,
        housing_request,
    )

    created = client.post(
        "/api/conversations",
        json={"request": valid_payload},
    )

    session_id = created.json()["id"]

    response = client.post(
        f"/api/conversations/{session_id}/decision",
        json={
            "expected_version": 1,
            "history_id": history_id,
        },
    )

    assert response.status_code == 200

    assert response.json()["current"]["history_id"] == (
        history_id
    )

    # 重复关联同一结果，不产生新版本。
    repeated = client.post(
        f"/api/conversations/{session_id}/decision",
        json={
            "expected_version": 1,
            "history_id": history_id,
        },
    )

    assert repeated.status_code == 200
    assert repeated.json()["current_version"] == 1


def test_mismatched_history_is_rejected(
    client,
    valid_payload,
    housing_request,
    history_repository,
):
    history_id = prepare_history(
        history_repository,
        housing_request,
    )

    created = client.post(
        "/api/conversations",
        json={
            "request": {
                **valid_payload,
                "monthly_budget": 6000,
            }
        },
    )

    session_id = created.json()["id"]

    response = client.post(
        f"/api/conversations/{session_id}/decision",
        json={
            "expected_version": 1,
            "history_id": history_id,
        },
    )

    assert response.status_code == 409

    loaded = client.get(
        f"/api/conversations/{session_id}"
    )

    assert loaded.json()["current"]["history_id"] is None


def test_old_result_cannot_bind_after_version_changes(
    client,
    valid_payload,
    housing_request,
    history_repository,
):
    history_id = prepare_history(
        history_repository,
        housing_request,
    )

    created = client.post(
        "/api/conversations",
        json={"request": valid_payload},
    )

    session_id = created.json()["id"]

    client.post(
        f"/api/conversations/{session_id}/versions",
        json={
            "expected_version": 1,
            "request": {
                **valid_payload,
                "monthly_budget": 6000,
            },
        },
    )

    response = client.post(
        f"/api/conversations/{session_id}/decision",
        json={
            "expected_version": 1,
            "history_id": history_id,
        },
    )

    assert response.status_code == 409

    current = client.get(
        f"/api/conversations/{session_id}"
    ).json()

    assert current["current_version"] == 2
    assert current["current"]["history_id"] is None