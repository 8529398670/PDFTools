# PDFTools API

Every route this server answers, apart from the pages at /login/*, /join/* and /docs/*. Generated from the code by scripts/api_docs.sh: an app's own routes get their docs the same way, and a test fails until they do.

This file is generated: do not edit it. Change the docs next to the handlers and run `scripts/api_docs.sh`.

## Contents

- [Calling the API](#calling-the-api)
- [Errors](#errors)
- [Account](#account)
- [Sign-in](#sign-in)
- [Files](#files)
- [Admin](#admin)
- [Owner](#owner)
- [Monitoring](#monitoring)
- [Schemas](#schemas)

## Calling the API

| Way in | How |
|---|---|
| Browser session | A browser session. Its POSTs carry csrf_token in the body. The cookie's name is server.cookie_name, with the __Host- prefix while server.secure_cookies is on. |
| API key | An API key, as Authorization: Bearer <id>.<secret>. |

## Errors

An error reply is a JSON object whose `error` says what went wrong.

| Status | Meaning | Body |
|---|---|---|
| 400 | The request was refused as it stands. | [`Error`](#error) |
| 401 | Not signed in. | [`Error`](#error) |
| 403 | Not allowed, or a bad csrf_token. | [`Error`](#error) |
| 404 | No such thing, or this feature is switched off. | [`Error`](#error) |
| 409 | The record has moved on: an undo too late, or a stale edit. | [`Error`](#error) |
| 429 | Too many requests. | [`Error`](#error) |
| 503 | In maintenance mode. Retry-After says when to try again. | [`Maintenance`](#maintenance) |

## Account

| Method | Path | Summary | Who may call |
|---|---|---|---|
| POST | [`/api/account/login-link`](#post-apiaccountlogin-link) | A login link for yourself | browser session or API key, anyone signed in |
| POST | [`/api/account/login-link/cancel`](#post-apiaccountlogin-linkcancel) | Stop your own login link working | browser session or API key, anyone signed in |
| POST | [`/api/account/rename`](#post-apiaccountrename) | Rename your account | browser session or API key, anyone signed in |
| GET | [`/api/account/sessions`](#get-apiaccountsessions) | Your signed-in devices | browser session or API key, anyone signed in |
| POST | [`/api/account/sessions/revoke-others`](#post-apiaccountsessionsrevoke-others) | Sign out every other device | browser session or API key, anyone signed in |
| POST | [`/api/account/sessions/{session_id}/label`](#post-apiaccountsessionssession_idlabel) | Name one of your devices | browser session or API key, anyone signed in |
| POST | [`/api/account/sessions/{session_id}/revoke`](#post-apiaccountsessionssession_idrevoke) | Sign out one of your devices | browser session or API key, anyone signed in |
| POST | [`/api/account/shortcuts`](#post-apiaccountshortcuts) | Change your keyboard shortcuts | browser session or API key, anyone signed in |
| POST | [`/api/account/theme`](#post-apiaccounttheme) | Pick your theme | browser session or API key, anyone signed in |
| POST | [`/api/account/themes`](#post-apiaccountthemes) | Replace your own themes | browser session or API key, anyone signed in |
| POST | [`/api/account/two-factor/confirm`](#post-apiaccounttwo-factorconfirm) | Turn two-factor on | browser session only, anyone signed in |
| POST | [`/api/account/two-factor/disable`](#post-apiaccounttwo-factordisable) | Turn two-factor off | browser session only, anyone signed in |
| POST | [`/api/account/two-factor/start`](#post-apiaccounttwo-factorstart) | Begin two-factor setup | browser session only, anyone signed in |
| POST | [`/api/bulk/account/sessions/revoke`](#post-apibulkaccountsessionsrevoke) | Sign out one of your devices, for many at once | browser session or API key, anyone signed in |
| GET | [`/api/language`](#get-apilanguage) | The UI's text | anyone |
| POST | [`/api/logout`](#post-apilogout) | Sign out | browser session or API key, anyone signed in |
| POST | [`/api/logs/events`](#post-apilogsevents) | Record what happened on the page | browser session or API key, anyone signed in |
| GET | [`/api/me`](#get-apime) | Who am I | browser session or API key, anyone signed in |
| GET | [`/api/team`](#get-apiteam) | List team | browser session or API key, anyone signed in |

### POST /api/account/login-link

A login link for yourself

A link that signs your own account in on a browser or another device. An API key may ask only if your account let it, from a browser session (POST /api/keys/{key_id}/sign-in); its link works once, for at most 15 minutes.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `expires_in_seconds` | integer | yes |  | 0 when it never expires. |
| `login_path` | string | yes |  | Path of the login link. A credential: treat it like a password. |
| `max_uses` | integer | yes |  | 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |

### POST /api/account/login-link/cancel

Stop your own login link working

Void your account's live login link without making a new one. Devices it already signed in stay signed in. Answers with removed: 0 or 1.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | integer | yes |  | Links removed: 0 or 1. |

### POST /api/account/rename

Rename your account

Change your own display name (1-80 characters). expect, when given, is the name you think it has now; if someone changed it meanwhile the rename is refused with the current name, so nothing is overwritten unseen.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `display_name` | string | yes | 1 to 80 characters |  |
| `expect` | string or null | no |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### GET /api/account/sessions

Your signed-in devices

Where your account is signed in, a page at a time: id, when it started and was last seen, the browser, and the name you gave it. Through an API key no device is current. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `sessions` | array of [`Session`](#session) | yes |  |  |
| `total` | integer | yes |  |  |

### POST /api/account/sessions/revoke-others

Sign out every other device

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | integer | yes |  |  |

### POST /api/account/sessions/{session_id}/label

Name one of your devices

Give one of your devices a name (at most 80 characters; empty clears it). expect, when given, is the name you think it has now.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `session_id` | path | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `label` | string | yes | at most 80 characters | At most 80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `label` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/account/sessions/{session_id}/revoke

Sign out one of your devices

End one of your signed-in sessions; that browser has to sign in again.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `session_id` | path | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/account/shortcuts

Change your keyboard shortcuts

Replace your changed keyboard shortcuts: action name to binding, such as "search": "Mod+K" (Mod is Cmd on a Mac, Ctrl elsewhere). Send the whole set; an empty binding switches a key off, and {} puts every key back to its default.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `shortcuts` | map of string | yes |  | Action name to binding, such as "search": "Mod+K". Mod is Cmd on a Mac and Ctrl elsewhere. Only changed shortcuts are listed; an empty binding switches that key off. Replaces the whole set; {} puts every key back to its default. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `shortcuts` | map of string | yes |  |  |

### POST /api/account/theme

Pick your theme

Switch to another theme from your list (or the defaults), by its id.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `theme_id` | string | yes |  | A theme's id. Empty for the first in the list. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `theme_id` | string | yes |  |  |

### POST /api/account/themes

Replace your own themes

Replace your whole list of color themes (1 to 40) and pick the one you use. themes: null goes back to following the app's defaults. A theme is the Theme schema in the API reference (config/api.json): id, name, mode light|dark, accent, second, and optional colors as #rrggbb.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `builtins` | integer | no |  | Which built-in themes this list has seen: the highest since in Theme.builtIn (static/js/theme.js) when it was saved. Built-in themes added after that join the list the browser shows. Left out: 0, the first ones. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `theme_id` | string | no |  | The theme you use. |
| `themes` | array of [`Theme`](#theme) or null | no |  | Your whole list, 1 to 40 themes. null goes back to following the app's defaults. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `theme_id` | string | yes |  |  |
| `themes` | array of [`Theme`](#theme) or null | yes |  | What you now see; null while the built-in themes apply. |
| `themes_builtins` | integer | yes |  | Which built-in themes that list has seen (see builtins on POST /api/account/themes). |
| `themes_custom` | boolean | yes |  |  |

### POST /api/account/two-factor/confirm

Turn two-factor on

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `code` | string | yes |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `recovery_codes` | array of string | yes |  |  |

### POST /api/account/two-factor/disable

Turn two-factor off

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `code` | string | yes |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/account/two-factor/start

Begin two-factor setup

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `secret` | string | yes |  |  |

### POST /api/bulk/account/sessions/revoke

Sign out one of your devices, for many at once

Runs POST /api/account/sessions/{session_id}/revoke once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### GET /api/language

The UI's text

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 429, 503 |

**Reply 200**: Success

An empty object.

### POST /api/logout

Sign out

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/logs/events

Record what happened on the page

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `events` | array of object | yes |  |  |
| `tab` | string | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `accepted` | integer | yes |  |  |

### GET /api/me

Who am I

The account this API key belongs to, the role it acts with (role -- never higher than the key's own scope), and the account's own role.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 401, 429, 503 |

**Reply 200**: Success

[`Me`](#me).

### GET /api/team

List team

People with an active account, a page at a time: id and display name.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `members` | array of [`Member`](#member) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

## Sign-in

| Method | Path | Summary | Who may call |
|---|---|---|---|
| POST | [`/api/login`](#post-apilogin) | Redeem a login link | anyone |
| POST | [`/api/login/two-factor`](#post-apilogintwo-factor) | Finish a sign-in with a code | anyone |

### POST /api/login

Redeem a login link

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  |  |

**Reply 200**: Success

[`SignIn`](#signin).

### POST /api/login/two-factor

Finish a sign-in with a code

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `challenge` | string | yes |  |  |
| `code` | string | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

## Files

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/account/storage`](#get-apiaccountstorage) | Your storage | browser session or API key, anyone signed in |
| GET | [`/api/admin/files`](#get-apiadminfiles) | List everyone's files | browser session or API key, admins |
| POST | [`/api/admin/files/{file_id}/delete`](#post-apiadminfilesfile_iddelete) | Delete anyone's file | browser session only, admins |
| GET | [`/api/admin/files/{file_id}/download`](#get-apiadminfilesfile_iddownload) | Download anyone's file | browser session only, admins |
| POST | [`/api/admin/files/{file_id}/rename`](#post-apiadminfilesfile_idrename) | Rename any file | browser session only, admins |
| POST | [`/api/admin/files/{file_id}/restore`](#post-apiadminfilesfile_idrestore) | Put back a deleted file | browser session only, admins |
| GET | [`/api/admin/storage`](#get-apiadminstorage) | Storage for everyone | browser session or API key, admins |
| POST | [`/api/bulk/files/delete`](#post-apibulkfilesdelete) | Delete a file, for many at once | browser session or API key, anyone signed in |
| POST | [`/api/bulk/files/restore`](#post-apibulkfilesrestore) | Restore a deleted file, for many at once | browser session or API key, anyone signed in |
| GET | [`/api/files`](#get-apifiles) | List your files | browser session or API key, anyone signed in |
| POST | [`/api/files`](#post-apifiles) | Start an upload | browser session or API key, anyone signed in |
| GET | [`/api/files/{file_id}`](#get-apifilesfile_id) | One of your files | browser session or API key, anyone signed in |
| POST | [`/api/files/{file_id}/chunks/{index}`](#post-apifilesfile_idchunksindex) | Send the next piece of an upload | browser session or API key, anyone signed in |
| POST | [`/api/files/{file_id}/delete`](#post-apifilesfile_iddelete) | Delete a file | browser session or API key, anyone signed in |
| GET | [`/api/files/{file_id}/download`](#get-apifilesfile_iddownload) | Download one of your files | browser session or API key, anyone signed in |
| POST | [`/api/files/{file_id}/finish`](#post-apifilesfile_idfinish) | Finish an upload | browser session or API key, anyone signed in |
| POST | [`/api/files/{file_id}/rename`](#post-apifilesfile_idrename) | Rename a file | browser session or API key, anyone signed in |
| POST | [`/api/files/{file_id}/restore`](#post-apifilesfile_idrestore) | Restore a deleted file | browser session or API key, anyone signed in |

### GET /api/account/storage

Your storage

How many bytes your files use, and your quota (0 is no limit).

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `quota_bytes` | integer | yes |  |  |
| `used_bytes` | integer | yes |  |  |

### GET /api/admin/files

List everyone's files

Every account's files, a page at a time, with whose each one is (user_id, user_name). next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep files whose name or owner contains this, in any case. |
| `sort` | query | string | no | one of `name`, `user_name`, `size`, `created_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `files` | array of object | yes |  |  |
| `files[].chunks` | integer | yes |  |  |
| `files[].created_at` | string (date-time) | yes |  |  |
| `files[].id` | string | yes |  |  |
| `files[].name` | string | yes |  |  |
| `files[].received` | integer | yes |  |  |
| `files[].size` | integer | yes |  |  |
| `files[].state` | string | yes | one of `uploading`, `ready` |  |
| `files[].type` | string | yes |  |  |
| `files[].user_id` | integer | yes |  |  |
| `files[].user_name` | string | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

### POST /api/admin/files/{file_id}/delete

Delete anyone's file

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | The file's id, from GET /api/admin/files (admin_list_files over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/admin/files/{file_id}/download

Download anyone's file

Written to the activity log when the file is someone else's.

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | The file's id, from GET /api/admin/files (admin_list_files over MCP). |

**Reply 200**: The file, always as an attachment

Raw bytes, as `application/octet-stream`.

### POST /api/admin/files/{file_id}/rename

Rename any file

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | The file's id, from GET /api/admin/files (admin_list_files over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `name` | string | yes |  | Cleaned like an upload's name. 1-255 bytes. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  | As stored. |
| `ok` | boolean | yes |  |  |

### POST /api/admin/files/{file_id}/restore

Put back a deleted file

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | The file's id, from GET /api/admin/files (admin_list_files over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`File`](#file).

### GET /api/admin/storage

Storage for everyone

How many bytes everyone's files use together, and the disk's free and total bytes where the system says.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 401, 403, 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `disk_free_bytes` | integer | no |  | Left out where the system will not say. |
| `disk_total_bytes` | integer | no |  | Left out where the system will not say. |
| `used_bytes` | integer | yes |  |  |

### POST /api/bulk/files/delete

Delete a file, for many at once

Runs POST /api/files/{file_id}/delete once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].file_id` | string | yes |  | The file's id, from GET /api/files (files_list over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/files/restore

Restore a deleted file, for many at once

Runs POST /api/files/{file_id}/restore once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].file_id` | string | yes |  | The file's id, from GET /api/files (files_list over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### GET /api/files

List your files

Your uploaded files, a page at a time: id, name, type, size, state (uploading or ready) and when. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep files whose name contains this, in any case. |
| `sort` | query | string | no | one of `name`, `size`, `created_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `files` | array of [`File`](#file) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

### POST /api/files

Start an upload

Then send each piece in order and finish. A file over files.max_file_bytes, or one that would pass files.quota_bytes_per_user, is a 409.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `name` | string | yes |  |  |
| `size` | integer | yes | at least 0 |  |
| `type` | string | no |  | Shown in the list. Downloads are always application/octet-stream. |

**Reply 201**: Created

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `chunk_bytes` | integer | yes |  | Every piece but the last is exactly this long. |
| `chunks` | integer | yes |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `id` | string | yes |  |  |
| `name` | string | yes |  |  |
| `received` | integer | yes |  |  |
| `size` | integer | yes |  |  |
| `state` | string | yes | one of `uploading`, `ready` |  |
| `type` | string | yes |  |  |

### GET /api/files/{file_id}

One of your files

One file: its details, and for an unfinished upload how many pieces have arrived (received), which is where to resume.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | The file's id, from GET /api/files (files_list over MCP). |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `chunk_bytes` | integer | yes |  | Every piece but the last is exactly this long. |
| `chunks` | integer | yes |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `id` | string | yes |  |  |
| `name` | string | yes |  |  |
| `received` | integer | yes |  |  |
| `size` | integer | yes |  |  |
| `state` | string | yes | one of `uploading`, `ready` |  |
| `type` | string | yes |  |  |

### POST /api/files/{file_id}/chunks/{index}

Send the next piece of an upload

The body is the raw bytes. Pieces go in order, from 0. A browser session sends its csrf token in the X-CSRF-Token header. A 409 carries received, the piece to send next. Counts against server.rate_limit_upload_max.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | The file's id, from GET /api/files (files_list over MCP). |
| `index` | path | integer | yes | at least 0 |  |
| `X-CSRF-Token` | header | string | no |  | From GET /api/me. Browser sessions only. |

**Request body**

Raw bytes, as `application/octet-stream`.

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `received` | integer | yes |  |  |

### POST /api/files/{file_id}/delete

Delete a file

Move one of your files to the bin. It can be restored for ten minutes; after that it is gone.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | The file's id, from GET /api/files (files_list over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/files/{file_id}/download

Download one of your files

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | The file's id, from GET /api/files (files_list over MCP). |

**Reply 200**: The file, always as an attachment

Raw bytes, as `application/octet-stream`.

### POST /api/files/{file_id}/finish

Finish an upload

Seal an upload once every piece has arrived; the file is then ready to download. Asked again, it answers the same. If pieces are missing it says how many arrived (received).

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | The file's id, from GET /api/files (files_list over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`File`](#file).

### POST /api/files/{file_id}/rename

Rename a file

Give one of your files a new name. expect, when given, is the name you think it has now; a rename made meanwhile is refused with the current name.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | The file's id, from GET /api/files (files_list over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `name` | string | yes |  | Cleaned like an upload's name. 1-255 bytes. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  | As stored. |
| `ok` | boolean | yes |  |  |

### POST /api/files/{file_id}/restore

Restore a deleted file

Bring back a file you deleted, while it is still in the bin and your storage quota has room.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | The file's id, from GET /api/files (files_list over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`File`](#file).

## Admin

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/admin/theme-defaults`](#get-apiadmintheme-defaults) | Default themes | browser session or API key, admins |
| POST | [`/api/admin/theme-defaults`](#post-apiadmintheme-defaults) | Replace the default themes | browser session or API key, admins |
| GET | [`/api/admin/users`](#get-apiadminusers) | List users | browser session or API key, admins |
| POST | [`/api/admin/users`](#post-apiadminusers) | Create an account | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/cancel-login-link`](#post-apiadminusersuser_idcancel-login-link) | Stop an account's login link working | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/delete`](#post-apiadminusersuser_iddelete) | Delete an account | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/disabled`](#post-apiadminusersuser_iddisabled) | Disable or enable a user | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/expiry`](#post-apiadminusersuser_idexpiry) | Set when an account expires | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/reissue-login`](#post-apiadminusersuser_idreissue-login) | A new login link for an account | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/rename`](#post-apiadminusersuser_idrename) | Rename someone | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/reset-two-factor`](#post-apiadminusersuser_idreset-two-factor) | Turn off an account's two-factor | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/revoke-access`](#post-apiadminusersuser_idrevoke-access) | Revoke a user's access | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/role`](#post-apiadminusersuser_idrole) | Change an account's role | browser session or API key, admins |
| GET | [`/api/admin/users/{user_id}/sessions`](#get-apiadminusersuser_idsessions) | An account's signed-in devices | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/sessions/{session_id}/revoke`](#post-apiadminusersuser_idsessionssession_idrevoke) | Sign out one of an account's devices | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/cancel-login-link`](#post-apibulkadminuserscancel-login-link) | Stop an account's login link working, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/delete`](#post-apibulkadminusersdelete) | Delete an account, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/disabled`](#post-apibulkadminusersdisabled) | Disable or enable a user, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/reset-two-factor`](#post-apibulkadminusersreset-two-factor) | Turn off an account's two-factor, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/revoke-access`](#post-apibulkadminusersrevoke-access) | Revoke a user's access, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/role`](#post-apibulkadminusersrole) | Change an account's role, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/sessions/revoke`](#post-apibulkadminuserssessionsrevoke) | Sign out one of an account's devices, for many at once | browser session or API key, admins |

### GET /api/admin/theme-defaults

Default themes

The theme list everyone without their own list sees. themes is null while the built-in ones apply.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 401, 403, 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `builtins` | integer | yes |  | Which built-in themes that list has seen (see builtins on POST /api/account/themes). |
| `themes` | array of [`Theme`](#theme) or null | yes |  | null while the built-in themes apply. |

### POST /api/admin/theme-defaults

Replace the default themes

Replace the theme list everyone without their own list sees, 1 to 40 themes in the Theme schema of the API reference. null puts the built-in themes back.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `builtins` | integer | no |  | Which built-in themes this list has seen: the highest since in Theme.builtIn (static/js/theme.js) when it was saved. Built-in themes added after that join the list the browser shows. Left out: 0, the first ones. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `themes` | array of [`Theme`](#theme) or null | no |  | 1 to 40 themes. null goes back to the built-in ones. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `builtins` | integer | yes |  | Which built-in themes that list has seen (see builtins on POST /api/account/themes). |
| `ok` | boolean | yes |  |  |
| `themes` | array of [`Theme`](#theme) or null | yes |  |  |

### GET /api/admin/users

List users

Accounts, a page at a time, including disabled ones, with each one's role and which is the owner. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep accounts whose name or username contains this, in any case. |
| `sort` | query | string | no | one of `display_name`, `role`, `disabled`, `created_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |
| `users` | array of [`User`](#user) | yes |  |  |

### POST /api/admin/users

Create an account

Make a new account and its first login link, to hand to the person. role is admin, user or viewer (reads only). account_expires_at, when given, is when the account stops working. Answers with user_id and the link.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `account_expires_at` | string (date-time) or null | no |  | When the account stops working (RFC 3339). Left out: never. expires_in_minutes is the login link's expiry, not this. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `display_name` | string | yes | 1 to 80 characters |  |
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `kind` | string | no | one of `person`, `service`; default `person` | person, the default. service is refused (403 service_account): a service account is made by Connect on the owner's API keys screen. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |

**Reply 201**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `expires_in_seconds` | integer | yes |  | 0 when it never expires. |
| `login_path` | string | yes |  | Path of the login link. A credential: treat it like a password. |
| `max_uses` | integer | yes |  | 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |
| `user_id` | integer | yes |  |  |

### POST /api/admin/users/{user_id}/cancel-login-link

Stop an account's login link working

Void an account's live login link without making a new one: a link that went somewhere it should not have.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | integer | yes |  | Links removed: 0 or 1. |

### POST /api/admin/users/{user_id}/delete

Delete an account

Remove an account for good, with its sessions, login link and API keys.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | [`Revoked`](#revoked) | yes |  |  |

### POST /api/admin/users/{user_id}/disabled

Disable or enable a user

Switch an account off (disabled: true) or back on (false). Disabling signs it out everywhere and voids its live login link; its API keys stop working while it is off. Reversible. The owner and your own account cannot be disabled.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `disabled` | boolean | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/expiry

Set when an account expires

expires_at is when the account stops working (RFC 3339), or null for never. Once it passes the account counts as disabled: sign-in, its sessions and its keys stop, and housekeeping disables it and revokes its access. A later expiry does not re-enable an account housekeeping already disabled. It must be in the future. The owner's account never expires, nobody sets their own, and only the owner sets an admin's.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_at` | string (date-time) or null | yes |  | When the account stops working (RFC 3339), or null for never. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/reissue-login

A new login link for an account

For someone who lost their device or their link: a fresh login link for their account.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `expires_in_seconds` | integer | yes |  | 0 when it never expires. |
| `login_path` | string | yes |  | Path of the login link. A credential: treat it like a password. |
| `max_uses` | integer | yes |  | 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/rename

Rename someone

Change another account's display name (1-80 characters). Only the owner renames an admin. expect, when given, is the name you think it has now; if it changed meanwhile the rename is refused with the current name.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `display_name` | string | yes | 1 to 80 characters | 1-80 characters. |
| `expect` | string or null | no |  | The name you think they have. Answers 409 if it is another. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/reset-two-factor

Turn off an account's two-factor

For someone who lost both their phone and their recovery codes: switches their two-factor sign-in off so a login link lets them in again. Only the owner resets an admin's; the owner's is reset from a shell.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/revoke-access

Revoke a user's access

For an account that may be compromised: ends every session and voids its live login link and every API key it holds, at once.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `revoked` | [`Revoked`](#revoked) | yes |  |  |

### POST /api/admin/users/{user_id}/role

Change an account's role

Make an account an admin, an ordinary user, or a viewer, who may read but change nothing. Only the owner takes an admin's rights away; the owner is always an admin, and nobody changes their own role. Becoming an admin ends the account's sessions and live login link.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `role` | string | yes |  |  |

### GET /api/admin/users/{user_id}/sessions

An account's signed-in devices

Where an account is signed in: every session, with when it started and was last seen. Addresses are shown to the owner and service accounts only. Nobody sees the owner's, and only the owner sees another admin's.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `sessions` | array of [`Session`](#session) | yes |  |  |
| `total` | integer | yes |  |  |

### POST /api/admin/users/{user_id}/sessions/{session_id}/revoke

Sign out one of an account's devices

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `session_id` | path | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/bulk/admin/users/cancel-login-link

Stop an account's login link working, for many at once

Runs POST /api/admin/users/{user_id}/cancel-login-link once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/delete

Delete an account, for many at once

Runs POST /api/admin/users/{user_id}/delete once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/disabled

Disable or enable a user, for many at once

Runs POST /api/admin/users/{user_id}/disabled once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].disabled` | boolean | no |  |  |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.disabled` | boolean | no |  |  |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/reset-two-factor

Turn off an account's two-factor, for many at once

Runs POST /api/admin/users/{user_id}/reset-two-factor once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/revoke-access

Revoke a user's access, for many at once

Runs POST /api/admin/users/{user_id}/revoke-access once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/role

Change an account's role, for many at once

Runs POST /api/admin/users/{user_id}/role once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].role` | string | no | one of `admin`, `user`, `viewer` |  |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.role` | string | no | one of `admin`, `user`, `viewer` |  |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/sessions/revoke

Sign out one of an account's devices, for many at once

Runs POST /api/admin/users/{user_id}/sessions/{session_id}/revoke once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

## Owner

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/owner/jobs`](#get-apiownerjobs) | Background jobs | browser session only, the owner |
| POST | [`/api/owner/jobs/{name}/run`](#post-apiownerjobsnamerun) | Run a job now | browser session only, the owner |
| GET | [`/api/owner/logs/days`](#get-apiownerlogsdays) | The days on record | browser session only, the owner |
| GET | [`/api/owner/logs/days/{date}`](#get-apiownerlogsdaysdate) | One day's entries | browser session only, the owner |
| POST | [`/api/owner/logs/days/{date}/delete`](#post-apiownerlogsdaysdatedelete) | Delete one day | browser session only, the owner |
| GET | [`/api/owner/logs/days/{date}/download`](#get-apiownerlogsdaysdatedownload) | One day's entries as a file | browser session only, the owner |
| GET | [`/api/owner/logs/ip-names`](#get-apiownerlogsip-names) | What the owner calls addresses | browser session only, the owner |
| POST | [`/api/owner/logs/ip-names`](#post-apiownerlogsip-names) | Name an address or a range, or rename one | browser session only, the owner |
| POST | [`/api/owner/logs/ip-names/delete`](#post-apiownerlogsip-namesdelete) | Take a name off an address or a range | browser session only, the owner |
| POST | [`/api/owner/logs/prune`](#post-apiownerlogsprune) | Apply the retention rules now | browser session only, the owner |
| GET | [`/api/owner/logs/stream`](#get-apiownerlogsstream) | New log entries as they happen | browser session only, the owner |
| GET | [`/api/owner/settings`](#get-apiownersettings) | config.yaml, as a form | browser session only, the owner |
| POST | [`/api/owner/settings`](#post-apiownersettings) | Save settings | browser session only, the owner |

### GET /api/owner/jobs

Background jobs

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `jobs` | array of [`Job`](#job) | yes |  |  |

### POST /api/owner/jobs/{name}/run

Run a job now

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `name` | path | string | yes |  | The job's name, from GET /api/owner/jobs. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 202**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/owner/logs/days

The days on record

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `q` | query | string | no |  | The Logs screen's search. |

**Reply 200**: Success

[`LogDays`](#logdays).

### GET /api/owner/logs/days/{date}

One day's entries

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `date` | path | string | yes |  | The day's date, from GET /api/owner/logs/days. |
| `q` | query | string | no |  | The Logs screen's search. |
| `before` | query | integer or null | no | at least 0 |  |
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |

**Reply 200**: Success

[`LogDay`](#logday).

### POST /api/owner/logs/days/{date}/delete

Delete one day

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `date` | path | string | yes |  | The day's date, from GET /api/owner/logs/days. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `deleted` | boolean | yes |  |  |

### GET /api/owner/logs/days/{date}/download

One day's entries as a file

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `date` | path | string | yes |  | The day's date, from GET /api/owner/logs/days. |

**Reply 200**: Success

Text, as `application/x-ndjson`.

### GET /api/owner/logs/ip-names

What the owner calls addresses

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 403, 404, 429, 503 |

**Reply 200**: Success

[`IPNames`](#ipnames).

### POST /api/owner/logs/ip-names

Name an address or a range, or rename one

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `name` | string | yes | 1 to 80 characters |  |
| `target` | string | yes | e.g. `10.0.0.0/24` | An address, or a range such as 10.0.0.0/24. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |
| `target` | string | yes |  |  |

### POST /api/owner/logs/ip-names/delete

Take a name off an address or a range

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `target` | string | yes | e.g. `10.0.0.0/24` | An address, or a range such as 10.0.0.0/24. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `deleted` | boolean | yes |  |  |

### POST /api/owner/logs/prune

Apply the retention rules now

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`PruneResult`](#pruneresult).

### GET /api/owner/logs/stream

New log entries as they happen

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `q` | query | string | no |  | The Logs screen's search. |

**Reply 200**: Success

Text, as `text/event-stream`.

### GET /api/owner/settings

config.yaml, as a form

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 404, 429, 503 |

**Reply 200**: Success

[`SettingsSnapshot`](#settingssnapshot).

### POST /api/owner/settings

Save settings

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `changes` | object | yes |  | Setting paths and their new values. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `version` | string | yes |  |  |

**Reply 200**: Success

[`SettingsResult`](#settingsresult).

## Monitoring

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/api.json`](#get-apiapijson) | This document | browser session or API key, anyone signed in |
| GET | [`/api/api.md`](#get-apiapimd) | The API reference as Markdown tables for people | browser session or API key, anyone signed in |
| GET | [`/api/health`](#get-apihealth) | Is the process up | anyone |
| GET | [`/api/ready`](#get-apiready) | Can the server do real work | anyone |

### GET /api/api.json

This document

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

An empty object.

### GET /api/api.md

The API reference as Markdown tables for people

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

Text, as `text/markdown`.

### GET /api/health

Is the process up

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/ready

Can the server do real work

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

## Schemas

The shapes the routes above refer to by name.

### BulkReply

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `done` | integer | yes |  | How many items worked. |
| `failed` | integer | yes |  | How many did not. |
| `results` | array of [`BulkResult`](#bulkresult) | yes |  | One per item, in the order they were sent. |

### BulkResult

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `error` | string | no |  | When it failed: the route's words for why. |
| `index` | integer | yes |  | The item's place in items, from 0. |
| `ok` | boolean | yes |  |  |
| `reply` | object | no |  | When it worked: the route's own reply, if it has one. |
| `request_id` | string | no |  | On a 5xx: the reference that finds this failure in the log. |
| `status` | integer | no |  | When it failed: the status the route would have answered. |

### Error

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `code` | string | no | one of `not_authenticated`, `not_admin`, `view_only`, `session_only`, `owner_required`, `owner_protected`, `key_minting_off`, `service_account`, `not_found`, `invalid`, `conflict`, `rate_limited`, `forbidden` | On a 4xx: why, for a program to branch on (error is for a person). The list is closed. |
| `error` | string | yes |  |  |
| `field` | string | no |  | On a 400 about one field: its name. |
| `request_id` | string | no |  | On a 5xx: the reference that finds this failure in the log. |

### File

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `chunks` | integer | yes |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `id` | string | yes |  |  |
| `name` | string | yes |  |  |
| `received` | integer | yes |  |  |
| `size` | integer | yes |  |  |
| `state` | string | yes | one of `uploading`, `ready` |  |
| `type` | string | yes |  |  |

### IPNames

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `names` | array of object | yes |  |  |
| `names[].created_at` | string (date-time) | yes |  |  |
| `names[].name` | string | yes |  |  |
| `names[].target` | string | yes |  |  |

### Job

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `interrupted` | boolean | yes |  |  |
| `interval_seconds` | integer | yes |  |  |
| `last_error` | string | no |  |  |
| `last_finished` | string (date-time) | no |  |  |
| `last_note` | string | no |  |  |
| `last_ok` | boolean or null | no |  |  |
| `last_started` | string (date-time) | no |  |  |
| `name` | string | yes |  |  |
| `next_due` | string (date-time) | yes |  |  |
| `running` | boolean | yes |  |  |
| `runs` | integer | yes |  |  |

### LogDay

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `date` | string | yes |  |  |
| `entries` | array of object | yes |  |  |
| `next` | integer or null | yes |  |  |

### LogDays

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `days` | array of object | yes |  |  |
| `dropped` | integer | yes |  |  |
| `settings` | object | yes |  |  |
| `total_bytes` | integer | yes |  |  |

### LoginLink

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `last_used_at` | string (date-time) or null | yes |  |  |
| `max_uses` | integer | yes |  | Sign-ins it allows. 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |
| `uses` | integer | yes |  | Sign-ins so far. |

### Maintenance

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `error` | string | yes |  |  |
| `maintenance` | string | yes | one of `read_only`, `full` |  |

### Me

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `account_role` | string | yes | one of `admin`, `user`, `viewer` |  |
| `announcement` | string | yes |  | server.announcement. Empty when there is none. |
| `api_doc_url` | string | yes |  | Where to read the API reference as a page for people: config/api.md in app.repo, or /docs/api when there is no repo. |
| `auth` | string | yes |  |  |
| `authenticated` | boolean | yes |  |  |
| `capabilities` | array of string | yes |  | The optional parts of that contract this app has on now: viewer_role, account_expiry, key_minting, invite_links, key_sign_in, service_accounts, key_grants, error_codes, key_rotation, admin_sessions. |
| `contract` | integer | yes |  | Which version of the portal contract this app speaks: the Portal contract section of the webserver skills' SKILL.md. |
| `csrf_token` | string | no |  | Browser sessions only. |
| `description` | string | yes |  | app.description. Empty when there is none. |
| `display_name` | string | yes |  |  |
| `files_enabled` | boolean | yes |  | files.enabled: whether the Files screen and routes are on. |
| `id` | integer | yes |  |  |
| `is_owner` | boolean | yes |  |  |
| `kind` | string | yes | one of `person`, `service` | person, or service for an account that only has API keys and is never signed into (ProjectPortal's own). |
| `login_link` | [`LoginLink`](#loginlink) or null | yes |  | Your own live login link, or null. |
| `logs_enabled` | boolean | yes |  |  |
| `logs_ui_clicks` | boolean | yes |  |  |
| `maintenance` | string | yes | one of `none`, `read_only`, `full` |  |
| `openapi_url` | string | yes |  | Where to read this API's reference: config/api.json in app.repo, or /api/api.json when there is no repo. |
| `owner` | boolean | yes |  | Whether this is the owner's account: the same as is_owner, under portal contract v3's name. |
| `repo` | string | yes |  | app.repo without a trailing / or .git: where the source lives. Empty when it is not set. |
| `role` | string | yes | one of `admin`, `user`, `viewer` | The effective role: never higher than an API key's own. A viewer may read, and change nothing. |
| `shortcuts` | map of string | yes |  | The keyboard shortcuts you changed, by action. Mod is Cmd on a Mac and Ctrl elsewhere. |
| `show_about` | boolean | yes |  | app.show_about: whether the menu has About. |
| `skill` | string | no |  | The webserver skill this app was scaffolded from (go-webserver or python-webserver), from its .skill-origin.yaml. Absent when that is not known. |
| `skill_commit` | string | no |  | The skill's commit this app was scaffolded from or last upgraded to, from its .skill-origin.yaml. Absent when that is not known. |
| `theme_id` | string | yes |  | The theme you use. Empty: the first. |
| `themes` | array of [`Theme`](#theme) or null | yes |  | Your themes (see the Theme schema): your own list, else the app's defaults, else null for the built-in ones. |
| `themes_builtins` | integer | yes |  | Which built-in themes that list has seen (see builtins on POST /api/account/themes). |
| `themes_custom` | boolean | yes |  | Whether you have your own list rather than following the defaults. |
| `two_factor` | boolean | yes |  |  |
| `two_factor_enabled` | boolean | yes |  |  |
| `version` | string | yes |  | The running build. dev when none was stamped. |

### Member

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `id` | integer | yes |  |  |

### PruneResult

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `bytes_after` | integer | yes |  |  |
| `bytes_before` | integer | yes |  |  |
| `compressed` | integer | yes |  |  |
| `deleted` | integer | yes |  |  |

### Revoked

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `login_links` | integer | yes |  |  |
| `sessions` | integer | yes |  |  |

### Session

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `current` | boolean | yes |  |  |
| `expires_at` | string (date-time) | yes |  |  |
| `id` | string | yes |  |  |
| `ip` | string | no |  |  |
| `ip_name` | string | no |  | What the owner calls this address on the Logs screen. The owner's own list only. |
| `label` | string | no |  | The name you gave this device. |
| `last_seen_at` | string (date-time) | no |  |  |
| `user_agent` | string | no |  |  |

### SettingsResult

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `applied` | array of string or null | yes |  |  |
| `changes` | array of object or null | yes |  |  |
| `restart` | array of string or null | yes |  |  |
| `scripts` | array of string or null | yes |  |  |
| `unchanged` | array of string or null | yes |  |  |
| `version` | string | yes |  |  |

### SettingsSnapshot

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `error` | object or null | yes |  |  |
| `error.at` | string (date-time) | yes |  |  |
| `error.message` | string | yes |  |  |
| `error.origin` | string | yes |  |  |
| `file` | string | yes |  |  |
| `in_container` | boolean | yes |  |  |
| `secret_file` | string | yes |  |  |
| `sections` | array of object | yes |  |  |
| `sections[].help` | string | yes |  |  |
| `sections[].keys` | array of object | yes |  |  |
| `sections[].keys[].apply` | string | yes |  |  |
| `sections[].keys[].default` | any | yes |  |  |
| `sections[].keys[].file_only` | boolean | yes |  | A path: change it in config.yaml, never here. |
| `sections[].keys[].help` | string | yes |  |  |
| `sections[].keys[].in_file` | boolean | yes |  |  |
| `sections[].keys[].key` | string | yes |  |  |
| `sections[].keys[].locked` | boolean | yes |  |  |
| `sections[].keys[].name` | string | yes |  |  |
| `sections[].keys[].pending_restart` | boolean | yes |  |  |
| `sections[].keys[].running` | any | yes |  |  |
| `sections[].keys[].type` | string | yes |  |  |
| `sections[].keys[].value` | any | yes |  |  |
| `sections[].name` | string | yes |  |  |
| `stale` | boolean | yes |  |  |
| `version` | string | yes |  | Send it back when saving: a changed file is refused with a 409. |
| `writable` | boolean | yes |  |  |

### SignIn

One of these:

1. An object:

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

2. An object:

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `challenge` | string | yes |  |  |
| `two_factor` | boolean | yes |  |  |

### Theme

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `accent` | string | yes |  | The main color: what you can press. |
| `background` | string | no |  | The page. Left out: the mode's own. |
| `button` | object or null | no |  | How the theme's buttons look. A choice left out is the default (rounded, normal, raised, normal). |
| `button.case` | string | no | one of `normal`, `upper` |  |
| `button.depth` | string | no | one of `flat`, `raised`, `glossy` |  |
| `button.shape` | string | no | one of `square`, `soft`, `rounded`, `pill` |  |
| `button.weight` | string | no | one of `normal`, `medium`, `bold` |  |
| `dark` | object or null | no |  | A light theme's colors for dark mode, kept while it is light. Switching the theme to dark swaps them in. A light theme's light (or a dark theme's dark) is dropped. |
| `dark.accent` | string | yes |  | The main color: what you can press. |
| `dark.background` | string | no |  | The page. Left out: the mode's own. |
| `dark.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, bar (the bar across the top), barText, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `dark.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `dark.surface` | string | no |  | Cards. Left out: the mode's own. |
| `id` | string | yes |  | Lower-case letters, digits, - and _, up to 32. |
| `light` | object or null | no |  | A dark theme's colors for light mode, kept while it is dark. Switching the theme to light swaps them in. |
| `light.accent` | string | yes |  | The main color: what you can press. |
| `light.background` | string | no |  | The page. Left out: the mode's own. |
| `light.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, bar (the bar across the top), barText, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `light.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `light.surface` | string | no |  | Cards. Left out: the mode's own. |
| `mode` | string | yes | one of `light`, `dark` |  |
| `name` | string | yes |  | 1 to 60 characters. |
| `overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, bar (the bar across the top), barText, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `surface` | string | no |  | Cards. Left out: the mode's own. |

### User

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `disabled` | boolean | yes |  | Switched off, or its expiry has passed. |
| `display_name` | string | yes |  |  |
| `expired` | boolean | yes |  | Whether expires_at has passed. |
| `expires_at` | string (date-time) or null | yes |  | When the account stops working, or null for never. |
| `id` | integer | yes |  |  |
| `kind` | string | yes | one of `person`, `service` | person, or service for an account with API keys only (ProjectPortal's own). |
| `login_link` | [`LoginLink`](#loginlink) or null | yes |  | The account's live login link, or null. |
| `owner` | boolean | yes |  |  |
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |
| `two_factor` | boolean | yes |  |  |
