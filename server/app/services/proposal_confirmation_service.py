"""Shared approval primitives for Hermes and LangGraph; no business execution here."""
import hashlib
import hmac
import json

from app.core.errors import AppError


def state_fingerprint(payload, *, ascii_json=False):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=ascii_json, sort_keys=True,
        separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def proposal_state_matches(proposal, signature):
    return hmac.compare_digest(proposal.expected_state_signature, signature)


def require_proposal_owner(proposal, organization_id, user_id):
    if proposal.organization_id != organization_id or proposal.user_id != user_id:
        raise AppError("hermes.proposal_not_found", "提案不存在或无权访问", 404)
