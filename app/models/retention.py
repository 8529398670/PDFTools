"""How long files are kept. Two layers:

- the global policy, which any admin sets: how long an account keeps what it
  imports and what actions make for it unless it says otherwise, and the
  longest anyone may keep anything;
- each account's own choice, which is clamped to that longest when it is saved
  and again whenever it is applied, so lowering the limit shortens everyone.

0 days means "keep until deleted". With max_days 0 there is no limit; with a
limit, nobody's 0 means forever: it means the limit.

A file's expiry is stamped on its record (files.expires_at) when it is made,
and every file's is worked out again when either layer changes, so the hourly
retention job only has to compare dates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.db import BUCKET_FILES, BUCKET_RETENTION, Record, Store
from app.models import from_iso, to_iso, utc_now
from app.models import files

GLOBAL_KEY = "global"
# The most days that can be typed anywhere: ten years.
DAYS_MAX = 3650


@dataclass
class Policy:
    import_days: int = 30
    output_days: int = 7
    max_days: int = 365
    updated_at: str | None = None
    updated_by: int | None = None


@dataclass
class Preference:
    # None follows the policy's default.
    import_days: int | None = None
    output_days: int | None = None


def _user_key(user_id: int) -> str:
    return f"user:{user_id}"


def get_policy(store: Store) -> Policy:
    record = store.get(BUCKET_RETENTION, GLOBAL_KEY) or {}
    return Policy(
        import_days=record.get("import_days", Policy.import_days),
        output_days=record.get("output_days", Policy.output_days),
        max_days=record.get("max_days", Policy.max_days),
        updated_at=record.get("updated_at"),
        updated_by=record.get("updated_by"),
    )


def set_policy(store: Store, import_days: int, output_days: int, max_days: int, actor_id: int) -> Policy:
    policy = Policy(import_days=import_days, output_days=output_days, max_days=max_days, updated_at=to_iso(utc_now()), updated_by=actor_id)
    store.put(BUCKET_RETENTION, GLOBAL_KEY, {
        "import_days": import_days,
        "output_days": output_days,
        "max_days": max_days,
        "updated_at": policy.updated_at,
        "updated_by": actor_id,
    })
    return policy


def get_preference(store: Store, user_id: int) -> Preference:
    record = store.get(BUCKET_RETENTION, _user_key(user_id)) or {}
    return Preference(import_days=record.get("import_days"), output_days=record.get("output_days"))


def set_preference(store: Store, user_id: int, import_days: int | None, output_days: int | None) -> Preference:
    """Saved clamped, so what the account sees is what applies."""
    policy = get_policy(store)
    preference = Preference(
        import_days=None if import_days is None else clamp(import_days, policy.max_days),
        output_days=None if output_days is None else clamp(output_days, policy.max_days),
    )
    store.put(BUCKET_RETENTION, _user_key(user_id), {"import_days": preference.import_days, "output_days": preference.output_days})
    return preference


def clamp(days: int, max_days: int) -> int:
    """days under the limit; 0 (keep) becomes the limit when there is one."""
    if max_days <= 0:
        return days
    return max_days if days <= 0 else min(days, max_days)


def effective_days(policy: Policy, preference: Preference, kind: str) -> int:
    """How many days a file of kind is kept for this account; 0 is forever."""
    if kind == files.KIND_OUTPUT:
        chosen = policy.output_days if preference.output_days is None else preference.output_days
    else:
        chosen = policy.import_days if preference.import_days is None else preference.import_days
    return clamp(chosen, policy.max_days)


def expiry_for(store: Store, user_id: int, kind: str, created_at: datetime | None = None) -> datetime | None:
    """When a file of kind made at created_at (now) by user_id expires."""
    days = effective_days(get_policy(store), get_preference(store, user_id), kind)
    if days <= 0:
        return None
    return (created_at or utc_now()) + timedelta(days=days)


def reapply(store: Store) -> int:
    """Work out every file's expiry again, after a change to either layer.
    Answers how many changed."""
    policy = get_policy(store)
    preferences: dict[int, Preference] = {}
    changed = 0
    for key, record in store.all(BUCKET_FILES):
        if record.get("keep"):
            continue  # chosen on a tool screen, not by the policy
        user_id = record["user_id"]
        if user_id not in preferences:
            preferences[user_id] = get_preference(store, user_id)
        days = effective_days(policy, preferences[user_id], record.get("kind", files.KIND_IMPORT))
        created = from_iso(record["created_at"])
        wanted = to_iso(created + timedelta(days=days)) if days > 0 and created else None
        if record.get("expires_at") != wanted:
            files.set_expiry(store, str(key), from_iso(wanted))
            changed += 1
    return changed


def expire_due(store: Store) -> int:
    """The hourly job's work: move every file past its expiry to the bin,
    where the files sweep removes it after the undo window. Answers how many."""
    now = utc_now()
    due = [
        str(key) for key, record in store.all(BUCKET_FILES)
        if record.get("deleted_at") is None and record.get("expires_at") and from_iso(record["expires_at"]) <= now
    ]
    for file_id in due:
        files.delete_file(store, file_id, None)  # type: ignore[arg-type]
    return len(due)


def record_of(policy: Policy) -> Record:
    return {"import_days": policy.import_days, "output_days": policy.output_days, "max_days": policy.max_days}
