"""How long files are kept: each account's own choice, and the policy any
admin sets for everyone. The rules are in app/models/retention.py."""
from __future__ import annotations

from typing import Annotated

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import ADMIN, Reply, route
from app.apidocs import Request as RequestType
from app.core.logs import KIND_ADMIN
from app.core.security import actor_from
from app.models import retention
from app.routes.helpers import DateTime, get_store
from app.routes.logs import audit

DAYS_ERROR = f"days must be 0-{retention.DAYS_MAX}"
Days = Annotated[int, Meta(ge=0, le=retention.DAYS_MAX, description="0 keeps until deleted (or up to the limit, when there is one).", extra={"error": DAYS_ERROR})]
MaybeDays = Annotated[Annotated[int, Meta(ge=0, le=retention.DAYS_MAX, extra={"error": DAYS_ERROR})] | None, Meta(description="null follows the default everyone gets.")]


class PolicyReply(Reply):
    import_days: Annotated[int, Meta(description="How long imports are kept unless an account says otherwise.")]
    output_days: Annotated[int, Meta(description="How long what actions make is kept unless an account says otherwise.")]
    max_days: Annotated[int, Meta(description="The longest anyone may keep anything; 0 is no limit.")]
    updated_at: DateTime | None


class MyRetention(Reply):
    import_days: Annotated[int | None, Meta(description="Your choice for imports; null follows the default.")]
    output_days: Annotated[int | None, Meta(description="Your choice for what actions make; null follows the default.")]
    effective_import_days: Annotated[int, Meta(description="What applies to your imports; 0 is until deleted.")]
    effective_output_days: Annotated[int, Meta(description="What applies to what actions make for you.")]
    policy: PolicyReply


def _policy_reply(policy: retention.Policy) -> PolicyReply:
    return PolicyReply(import_days=policy.import_days, output_days=policy.output_days, max_days=policy.max_days, updated_at=policy.updated_at)


def _mine(store: object, user_id: int) -> MyRetention:
    policy = retention.get_policy(store)  # type: ignore[arg-type]
    preference = retention.get_preference(store, user_id)  # type: ignore[arg-type]
    return MyRetention(
        import_days=preference.import_days,
        output_days=preference.output_days,
        effective_import_days=retention.effective_days(policy, preference, "import"),
        effective_output_days=retention.effective_days(policy, preference, "output"),
        policy=_policy_reply(policy),
    )


@route(
    "GET /api/account/retention", summary="How long your files are kept",
    tag="Retention", feature="files",
    description="Your own choice, what applies after the limit, and the policy everyone gets.",
)
def my_retention(request: Request) -> MyRetention:
    return _mine(get_store(request), actor_from(request).user.id)


class SetMyRetention(RequestType):
    import_days: MaybeDays = None
    output_days: MaybeDays = None


@route(
    "POST /api/account/retention", summary="Choose how long your files are kept",
    tag="Retention", feature="files",
    description="Each is clamped to the limit an admin set. Every one of your files gets its expiry worked "
    "out again from its import date.",
)
def set_my_retention(request: Request, body: SetMyRetention) -> MyRetention:
    store, user_id = get_store(request), actor_from(request).user.id
    retention.set_preference(store, user_id, body.import_days, body.output_days)
    retention.reapply(store)
    return _mine(store, user_id)


@route(
    "GET /api/admin/retention", summary="The retention policy",
    tag="Retention", role=ADMIN, feature="files",
)
def get_policy(request: Request) -> PolicyReply:
    return _policy_reply(retention.get_policy(get_store(request)))


class SetPolicy(RequestType):
    import_days: Days
    output_days: Days
    max_days: Annotated[int, Meta(ge=0, le=retention.DAYS_MAX, description="0 is no limit.", extra={"error": DAYS_ERROR})]


@route(
    "POST /api/admin/retention", summary="Set the retention policy",
    tag="Retention", role=ADMIN, feature="files",
    description="A default over the limit is kept as typed and applied up to the limit. Every file's expiry is worked out again, so lowering "
    "the limit shortens everyone's at once; files already past it go to the bin on the next retention run.",
)
def set_policy(request: Request, body: SetPolicy) -> PolicyReply:
    store = get_store(request)
    # Kept as typed: the limit applies when a default is used, so raising the
    # limit later brings the defaults back as they were meant.
    policy = retention.set_policy(store, body.import_days, body.output_days, body.max_days, actor_from(request).user.id)
    changed = retention.reapply(store)
    audit(request, KIND_ADMIN, "retention policy set", {**retention.record_of(policy), "files_changed": changed})
    return _policy_reply(policy)
