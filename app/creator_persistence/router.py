"""Composable internal Creator persistence API.

The router is intentionally not mounted in the public VELO FastAPI app. A
deployment must provide a real bearer-token authenticator and explicitly mount
this router on an internal-only service surface. Tests can compose the same
wire contract without creating a production authentication shortcut.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from .service import (
    CreatorAppendConflictError,
    CreatorAuthorizationError,
    CreatorPersistenceError,
    CreatorPersistenceService,
    CreatorPrincipal,
    CreatorProjectionError,
    CreatorProjectionRevisionMismatchError,
    CreatorStaleRevisionError,
)


CreatorTokenAuthenticator = Callable[[str], CreatorPrincipal]


def create_creator_internal_router(
    service: CreatorPersistenceService,
    authenticate_token: CreatorTokenAuthenticator,
) -> APIRouter:
    """Build the API only when the composition root supplies real auth."""

    router = APIRouter(prefix="/internal/creator", tags=["creator-internal"])

    def authenticated_principal(authorization: str | None = Header(default=None)) -> CreatorPrincipal:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail={"code": "missing_bearer_token"})
        token = authorization.removeprefix("Bearer ")
        if not token or token.strip() != token:
            raise HTTPException(status_code=401, detail={"code": "invalid_bearer_token"})
        try:
            return authenticate_token(token)
        except CreatorAuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": exc.code}) from exc

    @router.get("/workspaces/{workspace_id}")
    def read_workspace(
        workspace_id: str,
        principal: CreatorPrincipal = Depends(authenticated_principal),
    ) -> dict[str, Any]:
        try:
            return {"records": service.read_records(workspace_id, principal)}
        except CreatorAuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": exc.code}) from exc

    @router.get("/workspaces/{workspace_id}/projection-records")
    def read_projection_records(
        workspace_id: str,
        expected_revision: int = Query(ge=0),
        principal: CreatorPrincipal = Depends(authenticated_principal),
    ) -> dict[str, Any]:
        try:
            return service.read_projection_records(workspace_id, expected_revision, principal)
        except CreatorAuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": exc.code}) from exc
        except CreatorProjectionRevisionMismatchError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
        except CreatorProjectionError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code}) from exc

    @router.post("/workspaces/{workspace_id}/events")
    def append_event(
        workspace_id: str,
        body: dict[str, Any],
        principal: CreatorPrincipal = Depends(authenticated_principal),
    ) -> dict[str, Any]:
        if set(body) not in ({"event"}, {"event", "derivation_attestation"}) or not isinstance(body["event"], dict):
            raise HTTPException(status_code=422, detail={"code": "invalid_creator_append_body"})
        event = body["event"]
        if event.get("workspace_id") != workspace_id:
            raise HTTPException(status_code=409, detail={"code": "workspace_id_mismatch"})
        try:
            receipt = service.append(event, principal, body.get("derivation_attestation"))
        except CreatorAuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": exc.code}) from exc
        except (CreatorAppendConflictError, CreatorStaleRevisionError) as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
        except CreatorProjectionError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code}) from exc
        except CreatorPersistenceError as exc:
            raise HTTPException(status_code=500, detail={"code": exc.code}) from exc
        return {
            "event_id": receipt.event_id,
            "committed_revision": receipt.committed_revision,
            "payload_sha256": receipt.payload_sha256,
        }

    return router
