"""`python -m app manage ...` -- the handful of account operations that cannot
happen through the web UI, because they are needed before anyone can log in or
at the point when nobody can.

It opens the database directly, whether or not the server is running. SQLite
in WAL mode allows that: readers never block, and a write here waits its turn
behind the server's (up to the busy timeout) rather than failing. That is why
this template has no control socket, unlike the Go one -- bolt hands its file
to a single process, SQLite does not.

Every command goes through the same model functions the web routes use, so the
rules hold whichever door a change comes through: disabling an account kills
its sessions and live login links, and an API key can never outrank the
account that owns it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.core import bootstrap, config, db, rotate
from app.core import backup
from app.core import logs
from app.models import credentials, login_tokens, users

USAGE = """manage -- account administration for PDFTools

Usage:
  bootstrap-admin --name "Ada"          create the first admin + login link
  create-login    --name "Grace" [--role user] [--uses 5|unlimited] [--expires 7d|never]
  reissue-login   --user-id 3 [--uses 5|unlimited] [--expires 7d|never]
                                        fresh link for an existing user; once and
                                        30 minutes unless --uses/--expires say otherwise
  list-users                            id, name, role, status
  set-disabled    --user-id 3 [--enable]
  revoke-access   --user-id 3           end every session, login link and API key
  reset-2fa       --user-id 3           take two-factor sign-in off an account
  delete-user     --user-id 3 --yes     remove the account and everything it held
  transfer-owner  --user-id 3           make another enabled admin the owner
  backup          [--out path] [--include-key]
                                        one file with the database, config.yaml and
                                        storage, safe while the server runs
  restore         --from path --yes [--key-file path]
                                        put a backup back; the server must be stopped
  rotate-key      --yes                 move to a new secret key; the server must be
                                        stopped (in Docker: docker/rotate-key.sh)
  paths                                 where this app keeps its state
  logs            [--day 2026-11-02] [--q "status:5xx"] [--limit 50]
                                        the activity log: days, or one day's
                                        entries newest first, as JSON lines

The owner is the first admin, and the one account that can delete other
admins from the web UI. Nothing deletes or disables the owner -- move it with
transfer-owner first. delete-user cannot be undone, hence --yes.

A backup leaves secret.key out unless --include-key says otherwise, so keep a
copy of the key apart from your backups. Without it a backup cannot be read.
restore keeps what it replaces beside it, as app.db.before-restore-<time>. A
backup made under an older key needs --key-file, naming that key.

rotate-key re-encrypts the database, two-factor secrets and the activity log,
and everyone has to sign in again. The old key stays as
secret.key.retired-<time>, because every backup made before it still needs it.

These work whether or not the server is running, except restore and rotate-key:
the database is opened directly, which SQLite's WAL mode makes safe alongside a live server.

Every command reads the same config.yaml and secret.key as the server (see
"paths" for which). secret.key in particular must hold the key the data was
written with, or the stored records cannot be decrypted.
"""


class ManageError(Exception):
    """A command that cannot do what was asked. Shown as `error: <message>`."""


def add_link_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--uses", default="", help="how many sign-ins the link allows: a number (1-1000) or unlimited (default once)")
    parser.add_argument("--expires", default="", help="how long the link lasts: 30m, 12h, 7d, or never (default from config)")


def link_options(cfg: config.Config, args: argparse.Namespace) -> login_tokens.LinkOptions:
    """--uses and --expires, with the configured defaults filling the gaps."""
    try:
        max_uses, minutes = login_tokens.parse_link_flags(args.uses, args.expires)
    except ValueError as problem:
        raise ManageError(str(problem)) from None
    return login_tokens.resolve_link(max_uses, minutes, cfg.login_token_ttl_seconds, cfg.multi_use_login_token_ttl_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app manage", description=USAGE,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = commands.add_parser("bootstrap-admin", help="create the first admin + login link")
    p.add_argument("--name", required=True, help="display name for the first admin")
    p.add_argument("--force", action="store_true", help="create another admin even if one exists")

    p = commands.add_parser("create-login", help="create a user and print a login link")
    p.add_argument("--name", required=True, help="display name")
    p.add_argument("--role", choices=[users.ROLE_VIEWER, users.ROLE_USER, users.ROLE_ADMIN], default=users.ROLE_USER)
    add_link_arguments(p)

    p = commands.add_parser("reissue-login", help="fresh login link for an existing user")
    p.add_argument("--user-id", type=int, required=True)
    add_link_arguments(p)

    commands.add_parser("list-users", help="id, name, role, status")

    p = commands.add_parser("set-disabled", help="disable (or re-enable) an account")
    p.add_argument("--user-id", type=int, required=True)
    p.add_argument("--enable", action="store_true", help="re-enable instead of disabling")

    p = commands.add_parser("revoke-access", help="end every session, login link and API key")
    p.add_argument("--user-id", type=int, required=True)

    p = commands.add_parser("reset-2fa", help="take two-factor sign-in off an account")
    p.add_argument("--user-id", type=int, required=True)

    p = commands.add_parser("delete-user", help="remove an account and everything it held")
    p.add_argument("--user-id", type=int, required=True)
    p.add_argument("--yes", action="store_true", help="confirm: this cannot be undone")

    p = commands.add_parser("transfer-owner", help="make another enabled admin the owner")
    p.add_argument("--user-id", type=int, required=True)



    p = commands.add_parser("backup", help="one file with the database, config.yaml and storage")
    p.add_argument("--out", default="", help="a file to write, or a folder to write into (default: the backups folder)")
    p.add_argument("--include-key", action="store_true", help="put secret.key in the backup: anyone with the file can then read everything")

    p = commands.add_parser("restore", help="put a backup back; the server must be stopped")
    p.add_argument("--from", dest="source", required=True, help="the backup file")
    p.add_argument("--key-file", default="", help="the key this backup was made with, if it is not the current one")
    p.add_argument("--yes", action="store_true", help="confirm: the database and storage are replaced")

    p = commands.add_parser("rotate-key", help="move to a new secret key; the server must be stopped")
    p.add_argument("--new-key-file", default="", help="the new key, for docker/rotate-key.sh; empty means make one")
    p.add_argument("--yes", action="store_true", help="confirm: everyone has to sign in again")

    commands.add_parser("paths", help="where this app keeps its state")

    p = commands.add_parser("logs", help="the activity log: days, or one day's entries")
    p.add_argument("--day", default="", help="a UTC date, YYYY-MM-DD; without it, list the days")
    p.add_argument("--q", default="", help="a search, as typed on the Logs screen")
    p.add_argument("--limit", type=int, default=50, help="entries to print, newest first (1-1000)")
    return parser


def run(arguments: list[str]) -> None:
    args = build_parser().parse_args(arguments)
    try:
        cfg = config.load()
    except config.ConfigError as error:
        raise ManageError(f"config error: {error}") from None
    if cfg.secret_migrated:
        print(f"MOVED server.secret_key out of {cfg.config_file} into {cfg.secret_file} -- back it up with the database.", file=sys.stderr)

    # "paths" reports configuration only, so it never needs the database and
    # stays useful when everything else is failing.
    if args.command == "paths":
        command_paths(cfg)
        return
    # "logs" reads the log files, never the database, so it works the same
    # with the server up or down -- the files are only ever appended to.
    if args.command == "logs":
        command_logs(cfg, args)
        return

    if cfg.rotation_finished:
        print(f"[secret] finished a key rotation that had been cut short; the new key is in {cfg.secret_file}", file=sys.stderr)
    if args.command == "rotate-key":
        command_rotate_key(cfg, args)
        return
    if cfg.rotation_pending:
        raise ManageError(config.ROTATION_PENDING_MESSAGE)

    # "restore" replaces the database, so it must not depend on opening it --
    # it has to work on a database too damaged for anything else to read.
    if args.command == "restore":
        command_restore(cfg, args)
        return

    store = db.open_store(cfg.database_path, cfg.secret_key, cfg.encrypt_at_rest, cfg.app_dir / config.SERVER_LOCK_NAME)
    # A database written before the owner marker existed gets one here too,
    # so the owner rules hold for commands run before the server's first boot
    # on the new version.
    users.ensure_owner(store)
    # Say where this went. stderr, so piping list-users stays clean.
    print(f"[manage] database at {cfg.database_path}", file=sys.stderr)

    handlers = {
        "bootstrap-admin": command_bootstrap_admin,
        "create-login": command_create_login,
        "reissue-login": command_reissue_login,
        "list-users": command_list_users,
        "set-disabled": command_set_disabled,
        "revoke-access": command_revoke_access,
        "reset-2fa": command_reset_two_factor,
        "delete-user": command_delete_user,
        "transfer-owner": command_transfer_owner,
        "backup": command_backup,
    }
    try:
        handlers[args.command](store, cfg, args)
    except (
        backup.BackupError,
        db.DecodeError,
        credentials.OwnerProtectedError,
        users.NotAdminError,
    ) as error:
        raise ManageError(str(error)) from None


def require_user(store: db.Store, user_id: int) -> users.User:
    user = users.get_user(store, user_id)
    if user is None:
        raise ManageError(f"no user with id {user_id}")
    return user


def command_bootstrap_admin(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    if not users.valid_display_name(args.name):
        raise ManageError("--name must be 1-80 characters")
    if users.any_admin_exists(store) and not args.force:
        print("An admin already exists. Re-run with --force to create another.")
        return
    user = users.create_user(store, args.name, users.ROLE_ADMIN)
    credential, info = login_tokens.issue_login_link(store, user.id, login_tokens.once(cfg.login_token_ttl_seconds))
    bootstrap.print_login_link(cfg, f"admin #{user.id} {user.display_name!r}", credential, info)


def command_create_login(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    if not users.valid_display_name(args.name):
        raise ManageError("--name must be 1-80 characters")
    options = link_options(cfg, args)
    user = users.create_user(store, args.name, args.role)
    credential, info = login_tokens.issue_login_link(store, user.id, options)
    bootstrap.print_login_link(cfg, f"{user.role} #{user.id} {user.display_name!r}", credential, info)


def command_reissue_login(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    user = require_user(store, args.user_id)
    options = link_options(cfg, args)
    credential, info = login_tokens.issue_login_link(store, user.id, options)
    bootstrap.print_login_link(cfg, f"{user.role} #{user.id} {user.display_name!r}", credential, info)


def command_list_users(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    rows = users.list_users(store)
    if not rows:
        print('No users yet. Create the first admin with: python -m app manage bootstrap-admin --name "Your Name"')
        return
    owner_id = users.get_owner_id(store)
    print(f"{'ID':<6} {'NAME':<30} {'ROLE':<8} STATUS")
    for user in rows:
        status = "disabled" if user.disabled else "active"
        if user.id == owner_id:
            status += ", owner"
        print(f"{user.id:<6} {user.display_name:<30} {user.role:<8} {status}")


def command_set_disabled(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    user = require_user(store, args.user_id)
    disabled = not args.enable
    # Disabling deletes the account's sessions and live login links in the
    # same transaction -- see credentials.set_user_disabled.
    credentials.set_user_disabled(store, user.id, disabled)
    print(f"user #{user.id} ({user.display_name}) disabled={str(disabled).lower()}")


def command_revoke_access(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    """The incident-response command: run it when an account's credentials
    may be in someone else's hands. The account stays enabled; follow it with
    reissue-login to let its owner back in."""
    user = require_user(store, args.user_id)
    # The operator may revoke the owner's access too -- see
    # credentials.revoke_all_credentials.
    revoked = credentials.revoke_all_credentials(store, user.id, allow_owner=True)
    if revoked is None:
        raise ManageError(f"no user with id {user.id}")
    print(
        f"user #{user.id} ({user.display_name}): ended {revoked.sessions} sessions, deleted "
        f"{revoked.login_links} live login links"
    )
    print(f"To let them back in: python -m app manage reissue-login --user-id {user.id}")


def command_reset_two_factor(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    """The way back for someone with neither their phone nor their recovery
    codes -- the owner included, who no one can reset from the web."""
    user = require_user(store, args.user_id)
    credentials.reset_two_factor(store, user.id, None)
    print(f"user #{user.id} ({user.display_name}): two-factor sign-in is off")


def command_delete_user(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    """Asks for --yes because nothing brings the account back: the id is never
    reused and its keys and links are gone with it. Disabling is the
    reversible option, and the error says so. Acts as the operator (actor
    None): any account but the owner."""
    if not args.yes:
        raise ManageError(
            f"delete-user cannot be undone; re-run with --yes "
            f"(or use set-disabled --user-id {args.user_id} to keep the account)"
        )
    user = require_user(store, args.user_id)
    removed = credentials.delete_user(store, user.id, None)
    if removed is None:
        raise ManageError(f"no user with id {user.id}")
    print(
        f"user #{user.id} ({user.display_name}) deleted, with {removed.sessions} sessions, "
        f"{removed.login_links} login links"
    )


def command_transfer_owner(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    user = users.transfer_owner(store, args.user_id)
    if user is None:
        raise ManageError(f"no user with id {args.user_id}")
    print(f"user #{user.id} ({user.display_name}) is now the owner")


def command_backup(store: db.Store, cfg: config.Config, args: argparse.Namespace) -> None:
    result = backup.create(store, cfg, out=args.out, include_key=args.include_key)
    print(f"Backup written: {result.path} ({result.size} bytes)")
    if result.manifest.contains_key:
        print("WARNING: it includes secret.key. Anyone holding this file can read all the data.")
    else:
        print(f"secret.key is NOT in it. It needs the key with fingerprint {result.manifest.key_fingerprint}:")
        print("keep a copy of secret.key somewhere safe, apart from this file.")
    if not result.manifest.encrypt_at_rest:
        print("server.encrypt_at_rest is off, so the database in this backup is not encrypted.")


def command_restore(cfg: config.Config, args: argparse.Namespace) -> None:
    if not args.yes:
        raise ManageError("restore replaces the database and storage; pass --yes to confirm")
    try:
        result = backup.restore(cfg, args.source, key_file=args.key_file)
    except backup.BackupError as error:
        raise ManageError(str(error)) from None
    print(f"Restored the backup from {result.manifest.created_at}.")
    if result.rekeyed:
        print("It was made under another key and has been moved onto the current one.")
        print("Everyone has to sign in again, because their cookies were sealed with the other key.")
    if result.saved_database:
        print(f"The database it replaced: {result.saved_database}")
    if result.saved_storage:
        print(f"The storage it replaced:  {result.saved_storage}")
    if result.saved_config:
        print(f"config.yaml was left as it is; the backup's copy is at {result.saved_config}")


def command_rotate_key(cfg: config.Config, args: argparse.Namespace) -> None:
    # Loading the config just finished a rotation that was cut short, which is
    # what this command was probably run to do. Rotating again on top of it
    # is not.
    if cfg.rotation_finished:
        print("That finished the rotation that was cut short. Run this again to rotate once more.")
        return
    if not args.yes:
        raise ManageError("rotate-key signs everyone out and needs the server stopped; pass --yes to confirm")
    try:
        result = rotate.run(cfg, new_key_file=args.new_key_file)
    except rotate.RotateError as error:
        raise ManageError(str(error)) from None
    if result.resumed:
        print("Finished moving the data onto the new key.")
        return
    print(f"The data is on the new key (fingerprint {result.new_fingerprint}, was {result.old_fingerprint}).")
    if cfg.encrypt_at_rest:
        print(f"Re-encrypted the database and {result.log_files} log files.")
    if args.new_key_file:
        return
    print(f"The new key is in {cfg.secret_file}: back it up.")
    print("Everyone has to sign in again.")
    if result.retired_key:
        print(f"The old key is kept at {result.retired_key}")
        print("Backups made before now still need it: `manage restore --key-file` takes it. Delete it")
        print("once those backups no longer matter, and do not keep it beside them.")


def command_logs(cfg: config.Config, args: argparse.Namespace) -> None:
    reader = logs.Logger(cfg.logs, cfg.secret_key, cfg.encrypt_at_rest)
    query = logs.Query(args.q)
    if not args.day:
        days, total = reader.days(query)
        for row in days:
            line = f"{row['date']}  {row['entries']:7d} entries  {row['errors']:5d} errors  {row['bytes']:9d} bytes"
            if "matches" in row:
                line += f"  {row['matches']} matches"
            if row["compressed"]:
                line += "  (gzipped)"
            print(line)
        print(f"{total} bytes in {cfg.logs.dir}")
        return
    if not 1 <= args.limit <= 1000:
        raise ManageError("--limit must be 1-1000")
    try:
        records, _ = reader.read_day(args.day, query, -1, args.limit)
    except logs.BadDayError:
        raise ManageError("--day must be a date like 2026-11-02") from None
    for record in records:
        print(json.dumps(record, ensure_ascii=False))


def command_paths(cfg: config.Config) -> None:
    """Answers "where did it put my data", which is otherwise a question you
    can only settle by reading the source or the startup log."""

    def note(path: str) -> str:
        return "" if Path(path).exists() else "  (absent -- the bundled copy is used)"

    print(f"{'config':<14} {cfg.config_file}")
    print(f"{'secret':<14} {cfg.secret_file}  (the secret key: back it up with the database)")
    print(f"{'project dir':<14} {cfg.project_dir}  (relative paths in the config start here)")
    print(f"{'url':<14} {cfg.url}  (from {cfg.url_source})")
    print(f"{'app dir':<14} {cfg.app_dir}")
    print(f"{'database':<14} {cfg.database_path}  (plus -wal and -shm files while in use)")
    print(f"{'storage':<14} {cfg.storage_dir}")
    print(f"{'logs':<14} {cfg.logs.dir}")
    print(f"{'backups':<14} {cfg.backups.dir}")
    print(f"{'static':<14} {cfg.static_dir}{note(cfg.static_dir)}")
    print(f"{'language':<14} {cfg.language_file}{note(cfg.language_file)}")
    if cfg.config_warning:
        print(f"{'warning':<14} {cfg.config_warning}")

    # Whether the key sits inside the app dir decides what a backup has to
    # cover, so say which case this is rather than leaving it to be worked out
    # from the paths above.
    print("")
    print(f"Change any of these in {cfg.config_file} (server.app_dir moves the app dir).")
    if cfg.secret_file.parent == cfg.app_dir:
        print("Back up the app dir as a unit -- app.db is unreadable without secret.key.")
    else:
        print("secret.key is NOT in the app dir. Back up config.yaml, secret.key and the app")
        print("dir together; app.db is unreadable without secret.key.")
    print("`manage backup` is safe while the server runs. Copying app.db by hand is not: the")
    print("copy can miss writes still in app.db-wal.")
