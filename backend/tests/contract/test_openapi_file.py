"""docs/openapi.yaml — обязательный артефакт кейса: он должен совпадать со спецификацией из кода."""

import yaml
from fastapi import FastAPI

from app.scripts.export_openapi import DEFAULT_PATH, render

REQUIRED_ENDPOINTS = {
    ("post", "/api/v1/auth/login"),
    ("get", "/api/v1/auth/me"),
    ("post", "/api/v1/auth/logout"),
    ("get", "/api/v1/recurring-payments"),
    ("post", "/api/v1/recurring-payments"),
    ("delete", "/api/v1/recurring-payments/{payment_id}"),
    ("get", "/api/v1/payment-occurrences"),
    ("get", "/api/v1/payment-occurrences/{occurrence_id}"),
    ("patch", "/api/v1/payment-occurrences/{occurrence_id}"),
    ("get", "/api/v1/payments/summary"),
    ("get", "/api/v1/users"),
    ("post", "/api/v1/users"),
    ("patch", "/api/v1/users/{user_id}"),
    ("delete", "/api/v1/users/{user_id}"),
}


def test_openapi_file_is_up_to_date(app: FastAPI) -> None:
    assert DEFAULT_PATH.exists(), "нет docs/openapi.yaml — выполните: python -m app.scripts.export_openapi"
    committed = DEFAULT_PATH.read_text(encoding="utf-8")

    assert yaml.safe_load(committed) == yaml.safe_load(render(app.openapi())), (
        "docs/openapi.yaml устарел — выполните: python -m app.scripts.export_openapi"
    )


def test_all_required_endpoints_of_the_case_are_documented(app: FastAPI) -> None:
    documented = {(method, path) for path, operations in app.openapi()["paths"].items() for method in operations}

    assert documented >= REQUIRED_ENDPOINTS
