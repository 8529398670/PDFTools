# PDFTools API

Every route this server answers, apart from the pages at /login/*, /join/* and /docs/*. Generated from the code by scripts/api_docs.sh: an app's own routes get their docs the same way, and a test fails until they do.

This file is generated: do not edit it. Change the docs next to the handlers and run `scripts/api_docs.sh`.

## Contents

- [Calling the API](#calling-the-api)
- [Errors](#errors)
- [Account](#account)
- [Sign-in](#sign-in)
- [API keys](#api-keys)
- [Files](#files)
- [Admin](#admin)
- [Owner](#owner)
- [Monitoring](#monitoring)
- [Actions](#actions)
- [Retention](#retention)
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
| POST | [`/api/account/tool-modes`](#post-apiaccounttool-modes) | Choose where your tools run | browser session or API key, anyone signed in |
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

### POST /api/account/tool-modes

Choose where your tools run

Replace where your tools run: "*" is your default and a tool id an override for that tool, each auto (this device when it is up to it, else the server), device (in the browser, nothing uploaded) or server. Send the whole set; a tool left out follows your default, and {} puts everything back to auto.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `tool_modes` | map of string | yes |  | "*" for your default and a tool id for that tool's own override, each auto, device or server, such as {"*": "server", "split_bookmarks": "device"}. Replaces the whole set; a tool left out follows your default, and {} puts everything back to auto. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `tool_modes` | map of string | yes |  |  |

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

## API keys

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/admin/keys`](#get-apiadminkeys) | Every key in the app | browser session only, admins |
| POST | [`/api/admin/keys`](#post-apiadminkeys) | Create a key that acts as someone else | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/delete`](#post-apiadminkeyskey_iddelete) | Delete anyone's key | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/expiry`](#post-apiadminkeyskey_idexpiry) | Change when anyone's key expires | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/rename`](#post-apiadminkeyskey_idrename) | Rename anyone's key | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/restore`](#post-apiadminkeyskey_idrestore) | Undo deleting anyone's key | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/revoke`](#post-apiadminkeyskey_idrevoke) | Revoke anyone's key | browser session or API key, admins |
| GET | [`/api/admin/users/{user_id}/keys`](#get-apiadminusersuser_idkeys) | An account's keys | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/keys`](#post-apiadminusersuser_idkeys) | Make a key for an account | browser session or API key, admins |
| GET | [`/api/keys`](#get-apikeys) | Your API keys | browser session only, anyone signed in |
| POST | [`/api/keys`](#post-apikeys) | Create an API key | browser session only, anyone signed in |
| POST | [`/api/keys/self/rotate`](#post-apikeysselfrotate) | Rotate the calling key | API key only, anyone signed in |
| POST | [`/api/keys/{key_id}/delete`](#post-apikeyskey_iddelete) | Delete one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/expiry`](#post-apikeyskey_idexpiry) | Change when one of your keys expires | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/mint-keys`](#post-apikeyskey_idmint-keys) | Let one of your keys make keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/rename`](#post-apikeyskey_idrename) | Rename one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/restore`](#post-apikeyskey_idrestore) | Undo deleting one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/revoke`](#post-apikeyskey_idrevoke) | Revoke one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/rotate`](#post-apikeyskey_idrotate) | Rotate one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/sign-in`](#post-apikeyskey_idsign-in) | Let one of your keys make sign-in links | browser session only, anyone signed in |

### GET /api/admin/keys

Every key in the app

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep keys whose name or owner contains this, in any case. |
| `live` | query | string | no | one of `true` | Leave out revoked and expired keys. |
| `sort` | query | string | no | one of `display_name`, `name`, `role`, `last_used_at`, `expires_at`, `created_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `keys` | array of [`APIKey`](#apikey) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

### POST /api/admin/keys

Create a key that acts as someone else

Any admin may do this for an ordinary user, and only the owner for another admin. Nobody may do it for the owner. The key records who made it and shows that to the person it acts as.

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer or null | no | 0 to 3650 | Absent or null: the configured default. 0: never expires. |
| `name` | string | yes | 1 to 80 characters |  |
| `role` | string | no | one of `admin`, `user`, `viewer`; default `user` |  |
| `user_id` | integer | yes | at least 1 |  |

**Reply 201**: Success

[`NewAPIKey`](#newapikey).

### POST /api/admin/keys/{key_id}/delete

Delete anyone's key

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/keys/{key_id}/expiry

Change when anyone's key expires

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer | yes | 0 to 3650 | Counted from now. 0 means it never expires. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/admin/keys/{key_id}/rename

Rename anyone's key

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `name` | string | yes | 1 to 80 characters | 1-80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/admin/keys/{key_id}/restore

Undo deleting anyone's key

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/admin/keys/{key_id}/revoke

Revoke anyone's key

Stops the key at once, and every key it made, down the chain. Needs a browser session or a key with may_mint_keys (any other key gets 403 key_minting_off), which may not revoke the owner's keys.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/admin/users/{user_id}/keys

An account's keys

One account's keys, revoked and expired ones included, newest first. Each row says which key minted it (minted_by_key, empty when a person made it). Needs a browser session or a key with may_mint_keys; any other key gets 403 key_minting_off. Follows the owner ladder: nobody lists the owner's keys this way, and only the owner lists another admin's.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `keys` | array of [`APIKey`](#apikey) | yes |  |  |

### POST /api/admin/users/{user_id}/keys

Make a key for an account

Needs a browser session or a key the owner allowed to make keys (may_mint_keys); any other key gets 403 key_minting_off. The role is capped at the account's own; expires_in_days is required (1-365). Never for the owner. The new key records the key that made it, can never make keys or sign-in links itself, and is revoked when that key is revoked or deleted. Answers with the key and its credential, shown only now.

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
| `expires_in_days` | integer | yes | 1 to 365 | Required: 1-365. A minted key always expires. |
| `name` | string | yes | 1 to 80 characters |  |
| `role` | string | yes | one of `admin`, `user`, `viewer` | Capped at the account's own role. |

**Reply 201**: Success

[`NewAPIKey`](#newapikey).

### GET /api/keys

Your API keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep keys whose name contains this, in any case. |
| `live` | query | string | no | one of `true` | Leave out revoked and expired keys. |
| `sort` | query | string | no | one of `name`, `role`, `last_used_at`, `expires_at`, `created_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `keys` | array of [`APIKey`](#apikey) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

### POST /api/keys

Create an API key

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer or null | no | 0 to 3650 | Absent or null: the configured default. 0: never expires. |
| `name` | string | yes | 1 to 80 characters |  |
| `role` | string | no | one of `admin`, `user`, `viewer`; default `user` |  |

**Reply 201**: Success

[`NewAPIKey`](#newapikey).

### POST /api/keys/self/rotate

Rotate the calling key

Gives the calling key a new secret and answers its new credential, shown only now. The old secret stops working at once. The key's id, name, role, grants, lineage and expiry stay as they are, so the keys and links it made keep working; rotating never extends the expiry. A viewer key may call it.

|  |  |
|---|---|
| Who may call | API key only, anyone signed in |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`RotatedKey`](#rotatedkey).

### POST /api/keys/{key_id}/delete

Delete one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/keys/{key_id}/expiry

Change when one of your keys expires

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer | yes | 0 to 3650 | Counted from now. 0 means it never expires. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/keys/{key_id}/mint-keys

Let one of your keys make keys

Owner only, on one of your own admin-role keys. When on, the key may make keys for other accounts (never the owner's) through POST /api/admin/users/{user_id}/keys, list them, and revoke them. Each key it makes records it, and revoking or deleting this key revokes them all.

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `may_mint_keys` | boolean | yes |  | true lets this key make, list and revoke other accounts' keys, each recording this key and revoked with it. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/keys/{key_id}/rename

Rename one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `name` | string | yes | 1 to 80 characters | 1-80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/keys/{key_id}/restore

Undo deleting one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/keys/{key_id}/revoke

Revoke one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/keys/{key_id}/rotate

Rotate one of your keys

The owner only: gives one of the owner's own keys a new secret and answers its new credential, shown only now. The old secret stops working at once; nothing else about the key changes.

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`RotatedKey`](#rotatedkey).

### POST /api/keys/{key_id}/sign-in

Let one of your keys make sign-in links

Off by default. When on, the key may ask POST /api/account/login-link for a link that signs your account in on a browser, which then can do everything you can, including what keys may not. The link works once, for at most 15 minutes.

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `may_sign_in` | boolean | yes |  | true lets the key make a login link for your account: one that works once, for at most 15 minutes. |

**Reply 200**: Success

[`APIKey`](#apikey).

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
| POST | [`/api/claims`](#post-apiclaims) | Ask whether the server already has a file | browser session or API key, anyone signed in |
| POST | [`/api/claims/{claim_id}`](#post-apiclaimsclaim_id) | Answer a claim | browser session or API key, anyone signed in |
| GET | [`/api/files`](#get-apifiles) | List your files | browser session or API key, anyone signed in |
| POST | [`/api/files`](#post-apifiles) | Start an upload | browser session or API key, anyone signed in |
| GET | [`/api/files/{file_id}`](#get-apifilesfile_id) | One of your files | browser session or API key, anyone signed in |
| POST | [`/api/files/{file_id}/chunks/{index}`](#post-apifilesfile_idchunksindex) | Send one piece of an upload | browser session or API key, anyone signed in |
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
| `files[].bookmarks` | integer | yes |  | Bookmarks in all. |
| `files[].chunks` | integer | yes |  |  |
| `files[].created_at` | string (date-time) | yes |  |  |
| `files[].encrypted` | boolean | yes |  |  |
| `files[].expires_at` | string (date-time) or null | yes |  | When retention removes it; null keeps it. |
| `files[].folder` | string | yes |  | The folder it was dropped in with, relative to what was dropped. |
| `files[].id` | string | yes |  |  |
| `files[].kind` | string | yes | one of `import`, `output` |  |
| `files[].levels` | array of integer | yes |  | How many bookmarks sit at each level, from the top. |
| `files[].name` | string | yes |  |  |
| `files[].pages` | integer | yes |  |  |
| `files[].pdf_error` | string | yes |  | Why it could not be read: not_pdf, password or damaged. |
| `files[].pdf_state` | string | yes | one of `pending`, `ok`, `invalid` | pending until the first look has run. |
| `files[].received` | integer | yes |  |  |
| `files[].run_id` | string | yes |  | For an output, the run that made it. |
| `files[].size` | integer | yes |  |  |
| `files[].state` | string | yes | one of `uploading`, `ready` |  |
| `files[].title` | string | yes |  |  |
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

How many bytes everyone's files use together as quotas count them, what they take on disk with shared content stored once, and the disk's free and total bytes where the system says.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 401, 403, 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `disk_free_bytes` | integer | no |  | Left out where the system will not say. |
| `disk_total_bytes` | integer | no |  | Left out where the system will not say. |
| `stored_bytes` | integer | yes |  | What those files take on disk: content several files share is stored once. |
| `used_bytes` | integer | yes |  | Every account's files added up, the way quotas count them: a file several accounts hold counts for each. |

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

### POST /api/claims

Ask whether the server already has a file

Before uploading, say the file's fingerprint. When the server already holds that content (anyone's), it asks for the SHA-256 of a few random ranges of the file; a right answer to POST /api/claims/{claim_id} adds the file without sending it. The same checks as an upload come first: a file over files.max_file_bytes, or one that would pass your quota, is a 409. Ten minutes to answer.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `fingerprint` | string | yes |  | The file's content: SHA-256 over the SHA-256 of each 8 MiB piece of it in turn, as 64 lowercase hex digits. |
| `folder` | string | no |  | The folder it came in, relative to a dropped folder: shown, never a path on disk. |
| `keep` | string | no | one of ``, `run`, `day` | For an upload made to run a tool on: "run" deletes it once a run on it is done, "day" keeps it 24 hours, "" (the default) follows the retention policy. Either choice expires in 24 hours at the latest. |
| `name` | string | yes |  |  |
| `size` | integer | yes | at least 0 |  |
| `type` | string | no |  | Shown in the list. Downloads are always application/octet-stream. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `claim_id` | string | no |  | Where to send the answer. Empty when found is false. |
| `found` | boolean | yes |  | Whether the server already has this content. When it does not, upload the file as usual (POST /api/files). |
| `ranges` | array of array of integer | no |  | [offset, length] pairs: send the SHA-256 of each of these ranges of the file, in hex, in this order. Empty when found is false. |

### POST /api/claims/{claim_id}

Answer a claim

The SHA-256 of each range POST /api/claims asked for. Right, and the file is yours, ready, without being sent: it shares the bytes the server already has. Wrong, unknown or expired is a 403, and the file has to be uploaded. A claim is answered once.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `claim_id` | path | string | yes |  | From POST /api/claims. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `hashes` | array of string | yes |  | The SHA-256 of each range asked for, in hex, in the same order. |

**Reply 201**: Created

[`File`](#file).

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

Then send every piece, in any order and several at once, and finish. A file over files.max_file_bytes, or one that would pass files.quota_bytes_per_user, is a 409.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `folder` | string | no |  | The folder it came in, relative to a dropped folder: shown, never a path on disk. |
| `keep` | string | no | one of ``, `run`, `day` | For an upload made to run a tool on: "run" deletes it once a run on it is done, "day" keeps it 24 hours, "" (the default) follows the retention policy. Either choice expires in 24 hours at the latest. |
| `name` | string | yes |  |  |
| `size` | integer | yes | at least 0 |  |
| `type` | string | no |  | Shown in the list. Downloads are always application/octet-stream. |

**Reply 201**: Created

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `bookmarks` | integer | yes |  | Bookmarks in all. |
| `chunk_bytes` | integer | yes |  | Every piece but the last is exactly this long. |
| `chunks` | integer | yes |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `encrypted` | boolean | yes |  |  |
| `expires_at` | string (date-time) or null | yes |  | When retention removes it; null keeps it. |
| `folder` | string | yes |  | The folder it was dropped in with, relative to what was dropped. |
| `id` | string | yes |  |  |
| `kind` | string | yes | one of `import`, `output` |  |
| `levels` | array of integer | yes |  | How many bookmarks sit at each level, from the top. |
| `missing` | array of integer | yes |  | The pieces still to send, in any order: where to resume. |
| `name` | string | yes |  |  |
| `pages` | integer | yes |  |  |
| `pdf_error` | string | yes |  | Why it could not be read: not_pdf, password or damaged. |
| `pdf_state` | string | yes | one of `pending`, `ok`, `invalid` | pending until the first look has run. |
| `received` | integer | yes |  |  |
| `run_id` | string | yes |  | For an output, the run that made it. |
| `size` | integer | yes |  |  |
| `state` | string | yes | one of `uploading`, `ready` |  |
| `title` | string | yes |  |  |
| `type` | string | yes |  |  |

### GET /api/files/{file_id}

One of your files

One file: its details, and for an unfinished upload which pieces are still to send (missing), which is where to resume.

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
| `bookmarks` | integer | yes |  | Bookmarks in all. |
| `chunk_bytes` | integer | yes |  | Every piece but the last is exactly this long. |
| `chunks` | integer | yes |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `encrypted` | boolean | yes |  |  |
| `expires_at` | string (date-time) or null | yes |  | When retention removes it; null keeps it. |
| `folder` | string | yes |  | The folder it was dropped in with, relative to what was dropped. |
| `id` | string | yes |  |  |
| `kind` | string | yes | one of `import`, `output` |  |
| `levels` | array of integer | yes |  | How many bookmarks sit at each level, from the top. |
| `missing` | array of integer | yes |  | The pieces still to send, in any order: where to resume. |
| `name` | string | yes |  |  |
| `pages` | integer | yes |  |  |
| `pdf_error` | string | yes |  | Why it could not be read: not_pdf, password or damaged. |
| `pdf_state` | string | yes | one of `pending`, `ok`, `invalid` | pending until the first look has run. |
| `received` | integer | yes |  |  |
| `run_id` | string | yes |  | For an output, the run that made it. |
| `size` | integer | yes |  |  |
| `state` | string | yes | one of `uploading`, `ready` |  |
| `title` | string | yes |  |  |
| `type` | string | yes |  |  |

### POST /api/files/{file_id}/chunks/{index}

Send one piece of an upload

The body is the raw bytes. Pieces may come in any order and several at once; sending one that already arrived is harmless. A browser session sends its csrf token in the X-CSRF-Token header. Counts against server.rate_limit_upload_max.

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
| GET | [`/api/owner/portal`](#get-apiownerportal) | ProjectPortal's accounts | browser session only, the owner |
| POST | [`/api/owner/portal/connect`](#post-apiownerportalconnect) | Connect ProjectPortal | browser session only, the owner |
| POST | [`/api/owner/portal/disconnect`](#post-apiownerportaldisconnect) | Disconnect ProjectPortal | browser session only, the owner |
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

### GET /api/owner/portal

ProjectPortal's accounts

The service accounts ProjectPortal works through, each with its live keys and when they expire.

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `accounts` | array of [`PortalAccount`](#portalaccount) | yes |  | Every service account, oldest first. |

### POST /api/owner/portal/connect

Connect ProjectPortal

Makes the service account named name (ProjectPortal when left out) if there is none, and one admin key for it, lasting days (1-365), that may make keys for other accounts and never makes sign-in links. Answers with the key and its credential, shown only now: paste it into ProjectPortal as this app's admin key.

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `days` | integer | yes | 1 to 365 | How long the key lasts, in days. |
| `name` | string | no | 1 to 80 characters; default `ProjectPortal` | The service account's name. Left out: ProjectPortal. |

**Reply 201**: Success

[`NewAPIKey`](#newapikey).

### POST /api/owner/portal/disconnect

Disconnect ProjectPortal

Revokes every key of the service account user_id, and with them every key and link those keys made. The account stays, with no way in, until Connect gives it a key again.

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `user_id` | integer | yes |  | The service account. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `revoked` | integer | yes |  | Its keys revoked. The keys and links they made went with them. |

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

## Actions

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/actions`](#get-apiactions) | What can be done to a PDF | browser session or API key, anyone signed in |
| POST | [`/api/actions/{action}/start`](#post-apiactionsactionstart) | Start an action on many PDFs | browser session or API key, anyone signed in |
| POST | [`/api/files/{file_id}/actions/{action}`](#post-apifilesfile_idactionsaction) | Start an action on a PDF | browser session or API key, anyone signed in |
| GET | [`/api/runs`](#get-apiruns) | List your runs | browser session or API key, anyone signed in |
| GET | [`/api/runs/download`](#get-apirunsdownload) | Download everything several runs made | browser session or API key, anyone signed in |
| GET | [`/api/runs/stream`](#get-apirunsstream) | Hear when your runs or files change | browser session or API key, anyone signed in |
| GET | [`/api/runs/{run_id}`](#get-apirunsrun_id) | One of your runs | browser session or API key, anyone signed in |
| POST | [`/api/runs/{run_id}/cancel`](#post-apirunsrun_idcancel) | Cancel a run | browser session or API key, anyone signed in |
| POST | [`/api/runs/{run_id}/delete`](#post-apirunsrun_iddelete) | Delete a run | browser session or API key, anyone signed in |
| GET | [`/api/runs/{run_id}/download`](#get-apirunsrun_iddownload) | Download everything a run made | browser session or API key, anyone signed in |
| POST | [`/api/runs/{run_id}/restart`](#post-apirunsrun_idrestart) | Start a cancelled or failed run again | browser session or API key, anyone signed in |
| POST | [`/api/runs/{run_id}/restore`](#post-apirunsrun_idrestore) | Restore a deleted run | browser session or API key, anyone signed in |

### GET /api/actions

What can be done to a PDF

Each action and its options with their defaults. Words for them are in language.yaml under actions.<name>.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `actions` | array of object | yes |  |  |
| `actions[].defaults` | object | yes |  | Every option and the value it has unless one is sent. |
| `actions[].name` | string | yes |  |  |
| `actions[].needs_bookmarks` | boolean | yes |  |  |

### POST /api/actions/{action}/start

Start an action on many PDFs

One run per file, in one request: what a dropped folder needs. A file that cannot take the action is listed in skipped with why, and the rest still start.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `action` | path | string | yes |  | An action's name, from GET /api/actions. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `file_ids` | array of string | yes |  | Your imported PDFs, up to 1000. |
| `options` | object | no |  | The action's options, the same for every file. |

**Reply 201**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `runs` | array of object | yes |  |  |
| `runs[].action` | string | yes |  |  |
| `runs[].created_at` | string (date-time) | yes |  |  |
| `runs[].file_id` | string | yes |  |  |
| `runs[].file_name` | string | yes |  |  |
| `runs[].finished_at` | string (date-time) or null | yes |  |  |
| `runs[].id` | string | yes |  |  |
| `runs[].message` | string | yes |  | Why it failed, as a code. |
| `runs[].options` | object | yes |  |  |
| `runs[].output_bytes` | integer | yes |  |  |
| `runs[].outputs` | integer | yes |  | How many of the files it made are still here. |
| `runs[].progress` | number | yes |  | 0 to 1. |
| `runs[].result` | object | yes |  | What it reported when done, such as how many sections. |
| `runs[].started_at` | string (date-time) or null | yes |  |  |
| `runs[].state` | string | yes | one of `queued`, `running`, `done`, `failed`, `cancelled` |  |
| `runs[].step` | string | yes |  | What it is doing now: the file it is writing. |
| `skipped` | array of object | yes |  |  |
| `skipped[].error` | string | yes |  | Why it was not started: no such file, not_readable, no_bookmarks. |
| `skipped[].file_id` | string | yes |  |  |

### POST /api/files/{file_id}/actions/{action}

Start an action on a PDF

Queues a run and answers it. A file that is not a readable PDF, or one with no bookmarks for an action that needs them, is a 409.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `file_id` | path | string | yes |  | One of your imported PDFs. |
| `action` | path | string | yes |  | An action's name, from GET /api/actions. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `options` | object | no |  | The action's options; any left out take their default. |

**Reply 201**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `action` | string | yes |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `file_id` | string | yes |  |  |
| `file_name` | string | yes |  |  |
| `finished_at` | string (date-time) or null | yes |  |  |
| `id` | string | yes |  |  |
| `message` | string | yes |  | Why it failed, as a code. |
| `options` | object | yes |  |  |
| `output_bytes` | integer | yes |  |  |
| `outputs` | integer | yes |  | How many of the files it made are still here. |
| `progress` | number | yes |  | 0 to 1. |
| `result` | object | yes |  | What it reported when done, such as how many sections. |
| `started_at` | string (date-time) or null | yes |  |  |
| `state` | string | yes | one of `queued`, `running`, `done`, `failed`, `cancelled` |  |
| `step` | string | yes |  | What it is doing now: the file it is writing. |

### GET /api/runs

List your runs

Newest first unless sorted: each run, how far it has got, and how many files it made.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep runs whose file name contains this, in any case. |
| `sort` | query | string | no | one of `file_name`, `state`, `created_at` | Field to sort the whole list by. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `runs` | array of object | yes |  |  |
| `runs[].action` | string | yes |  |  |
| `runs[].created_at` | string (date-time) | yes |  |  |
| `runs[].file_id` | string | yes |  |  |
| `runs[].file_name` | string | yes |  |  |
| `runs[].finished_at` | string (date-time) or null | yes |  |  |
| `runs[].id` | string | yes |  |  |
| `runs[].message` | string | yes |  | Why it failed, as a code. |
| `runs[].options` | object | yes |  |  |
| `runs[].output_bytes` | integer | yes |  |  |
| `runs[].outputs` | integer | yes |  | How many of the files it made are still here. |
| `runs[].progress` | number | yes |  | 0 to 1. |
| `runs[].result` | object | yes |  | What it reported when done, such as how many sections. |
| `runs[].started_at` | string (date-time) or null | yes |  |  |
| `runs[].state` | string | yes | one of `queued`, `running`, `done`, `failed`, `cancelled` |  |
| `runs[].step` | string | yes |  | What it is doing now: the file it is writing. |
| `total` | integer | yes |  |  |

### GET /api/runs/download

Download everything several runs made

What a tool screen offers once a batch is done. A run that is not yours, or made nothing, is left out; none left is a 404.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `ids` | query | string | no |  | Your runs' ids, comma-separated, up to 1000. |

**Reply 200**: One zip, a folder per run named after its PDF, always as an attachment

Text, as `application/zip`.

### GET /api/runs/stream

Hear when your runs or files change

Server-sent events: "runs" when a run moves, "files" when an import has been read. Each only says something changed; fetch the list again.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 401, 403, 404, 429, 503 |

**Reply 200**: Success

Text, as `text/event-stream`.

### GET /api/runs/{run_id}

One of your runs

The run and the files it made, in order.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `run_id` | path | string | yes |  | The run's id, from GET /api/runs. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `action` | string | yes |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `file_id` | string | yes |  |  |
| `file_name` | string | yes |  |  |
| `files` | array of [`File`](#file) | yes |  |  |
| `finished_at` | string (date-time) or null | yes |  |  |
| `id` | string | yes |  |  |
| `message` | string | yes |  | Why it failed, as a code. |
| `options` | object | yes |  |  |
| `output_bytes` | integer | yes |  |  |
| `outputs` | integer | yes |  | How many of the files it made are still here. |
| `progress` | number | yes |  | 0 to 1. |
| `result` | object | yes |  | What it reported when done, such as how many sections. |
| `started_at` | string (date-time) or null | yes |  |  |
| `state` | string | yes | one of `queued`, `running`, `done`, `failed`, `cancelled` |  |
| `step` | string | yes |  | What it is doing now: the file it is writing. |

### POST /api/runs/{run_id}/cancel

Cancel a run

A queued run is cancelled at once, a running one at its next step; what it made so far goes to the bin.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `run_id` | path | string | yes |  | The run's id, from GET /api/runs. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/runs/{run_id}/delete

Delete a run

The run and every file it made go to the bin, and can be restored for ten minutes. A run still going is cancelled first.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `run_id` | path | string | yes |  | The run's id, from GET /api/runs. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/runs/{run_id}/download

Download everything a run made

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `run_id` | path | string | yes |  | The run's id, from GET /api/runs. |

**Reply 200**: A zip of the run's files, stored as they are, always as an attachment

Text, as `application/zip`.

### POST /api/runs/{run_id}/restart

Start a cancelled or failed run again

Queues the run again from the beginning, on the same file with the same options. A run that is queued, running or done, or one whose PDF is gone, is a 409.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `run_id` | path | string | yes |  | The run's id, from GET /api/runs. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `action` | string | yes |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `file_id` | string | yes |  |  |
| `file_name` | string | yes |  |  |
| `finished_at` | string (date-time) or null | yes |  |  |
| `id` | string | yes |  |  |
| `message` | string | yes |  | Why it failed, as a code. |
| `options` | object | yes |  |  |
| `output_bytes` | integer | yes |  |  |
| `outputs` | integer | yes |  | How many of the files it made are still here. |
| `progress` | number | yes |  | 0 to 1. |
| `result` | object | yes |  | What it reported when done, such as how many sections. |
| `started_at` | string (date-time) or null | yes |  |  |
| `state` | string | yes | one of `queued`, `running`, `done`, `failed`, `cancelled` |  |
| `step` | string | yes |  | What it is doing now: the file it is writing. |

### POST /api/runs/{run_id}/restore

Restore a deleted run

Brings back a run you deleted, with its files, while they are still in the bin.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `run_id` | path | string | yes |  | The run's id, from GET /api/runs. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `action` | string | yes |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `file_id` | string | yes |  |  |
| `file_name` | string | yes |  |  |
| `finished_at` | string (date-time) or null | yes |  |  |
| `id` | string | yes |  |  |
| `message` | string | yes |  | Why it failed, as a code. |
| `options` | object | yes |  |  |
| `output_bytes` | integer | yes |  |  |
| `outputs` | integer | yes |  | How many of the files it made are still here. |
| `progress` | number | yes |  | 0 to 1. |
| `result` | object | yes |  | What it reported when done, such as how many sections. |
| `started_at` | string (date-time) or null | yes |  |  |
| `state` | string | yes | one of `queued`, `running`, `done`, `failed`, `cancelled` |  |
| `step` | string | yes |  | What it is doing now: the file it is writing. |

## Retention

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/account/retention`](#get-apiaccountretention) | How long your files are kept | browser session or API key, anyone signed in |
| POST | [`/api/account/retention`](#post-apiaccountretention) | Choose how long your files are kept | browser session or API key, anyone signed in |
| GET | [`/api/admin/retention`](#get-apiadminretention) | The retention policy | browser session or API key, admins |
| POST | [`/api/admin/retention`](#post-apiadminretention) | Set the retention policy | browser session or API key, admins |

### GET /api/account/retention

How long your files are kept

Your own choice, what applies after the limit, and the policy everyone gets.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `effective_import_days` | integer | yes |  | What applies to your imports; 0 is until deleted. |
| `effective_output_days` | integer | yes |  | What applies to what actions make for you. |
| `import_days` | integer or null | yes |  | Your choice for imports; null follows the default. |
| `output_days` | integer or null | yes |  | Your choice for what actions make; null follows the default. |
| `policy` | object | yes |  |  |
| `policy.import_days` | integer | yes |  | How long imports are kept unless an account says otherwise. |
| `policy.max_days` | integer | yes |  | The longest anyone may keep anything; 0 is no limit. |
| `policy.output_days` | integer | yes |  | How long what actions make is kept unless an account says otherwise. |
| `policy.updated_at` | string (date-time) or null | yes |  |  |

### POST /api/account/retention

Choose how long your files are kept

Each is clamped to the limit an admin set. Every one of your files gets its expiry worked out again from its import date.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `import_days` | integer or null | no | 0 to 3650 | null follows the default everyone gets. |
| `output_days` | integer or null | no | 0 to 3650 | null follows the default everyone gets. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `effective_import_days` | integer | yes |  | What applies to your imports; 0 is until deleted. |
| `effective_output_days` | integer | yes |  | What applies to what actions make for you. |
| `import_days` | integer or null | yes |  | Your choice for imports; null follows the default. |
| `output_days` | integer or null | yes |  | Your choice for what actions make; null follows the default. |
| `policy` | object | yes |  |  |
| `policy.import_days` | integer | yes |  | How long imports are kept unless an account says otherwise. |
| `policy.max_days` | integer | yes |  | The longest anyone may keep anything; 0 is no limit. |
| `policy.output_days` | integer | yes |  | How long what actions make is kept unless an account says otherwise. |
| `policy.updated_at` | string (date-time) or null | yes |  |  |

### GET /api/admin/retention

The retention policy

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 401, 403, 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `import_days` | integer | yes |  | How long imports are kept unless an account says otherwise. |
| `max_days` | integer | yes |  | The longest anyone may keep anything; 0 is no limit. |
| `output_days` | integer | yes |  | How long what actions make is kept unless an account says otherwise. |
| `updated_at` | string (date-time) or null | yes |  |  |

### POST /api/admin/retention

Set the retention policy

A default over the limit is kept as typed and applied up to the limit. Every file's expiry is worked out again, so lowering the limit shortens everyone's at once; files already past it go to the bin on the next retention run.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `import_days` | integer | yes | 0 to 3650 | 0 keeps until deleted (or up to the limit, when there is one). |
| `max_days` | integer | yes | 0 to 3650 | 0 is no limit. |
| `output_days` | integer | yes | 0 to 3650 | 0 keeps until deleted (or up to the limit, when there is one). |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `import_days` | integer | yes |  | How long imports are kept unless an account says otherwise. |
| `max_days` | integer | yes |  | The longest anyone may keep anything; 0 is no limit. |
| `output_days` | integer | yes |  | How long what actions make is kept unless an account says otherwise. |
| `updated_at` | string (date-time) or null | yes |  |  |

## Schemas

The shapes the routes above refer to by name.

### APIKey

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `created_by` | integer | no |  | The admin who made this key for its owner. Absent if the owner made it. |
| `created_by_name` | string | no |  |  |
| `display_name` | string | no |  | The key's owner. On the admin list only. |
| `expired` | boolean | yes |  |  |
| `expires_at` | string (date-time) | no |  |  |
| `id` | string | yes |  |  |
| `last_used_at` | string (date-time) | no |  |  |
| `live` | boolean | yes |  |  |
| `may_mint_keys` | boolean | yes |  | Whether this key may make keys for other accounts. Only the owner switches it on. |
| `may_sign_in` | boolean | yes |  | Whether this key may make a login link for its own account. |
| `minted_by_key` | string | yes |  | The key that made this one, or empty. Revoking that key revokes this one. |
| `name` | string | yes |  |  |
| `revoked` | boolean | yes |  |  |
| `revoked_at` | string (date-time) | no |  |  |
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |
| `user_id` | integer | yes |  |  |

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
| `bookmarks` | integer | yes |  | Bookmarks in all. |
| `chunks` | integer | yes |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `encrypted` | boolean | yes |  |  |
| `expires_at` | string (date-time) or null | yes |  | When retention removes it; null keeps it. |
| `folder` | string | yes |  | The folder it was dropped in with, relative to what was dropped. |
| `id` | string | yes |  |  |
| `kind` | string | yes | one of `import`, `output` |  |
| `levels` | array of integer | yes |  | How many bookmarks sit at each level, from the top. |
| `name` | string | yes |  |  |
| `pages` | integer | yes |  |  |
| `pdf_error` | string | yes |  | Why it could not be read: not_pdf, password or damaged. |
| `pdf_state` | string | yes | one of `pending`, `ok`, `invalid` | pending until the first look has run. |
| `received` | integer | yes |  |  |
| `run_id` | string | yes |  | For an output, the run that made it. |
| `size` | integer | yes |  |  |
| `state` | string | yes | one of `uploading`, `ready` |  |
| `title` | string | yes |  |  |
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
| `api_key_id` | string | no |  | API keys only. |
| `api_key_name` | string | no |  | API keys only. |
| `api_keys_enabled` | boolean | yes |  |  |
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
| `key` | [`MeKey`](#mekey) | no |  | API keys only: what this key may do. |
| `kind` | string | yes | one of `person`, `service` | person, or service for an account that only has API keys and is never signed into (ProjectPortal's own). |
| `login_link` | [`LoginLink`](#loginlink) or null | yes |  | Your own live login link, or null. |
| `logs_enabled` | boolean | yes |  |  |
| `logs_ui_clicks` | boolean | yes |  |  |
| `maintenance` | string | yes | one of `none`, `read_only`, `full` |  |
| `may_mint_keys` | boolean | no |  | API keys only: whether this key may make keys for other accounts. |
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
| `tool_modes` | map of string | yes |  | Where your tools run: "*" is your default, and a tool id its own override; each is auto, device or server. Missing: auto, and a tool follows your default. |
| `two_factor` | boolean | yes |  |  |
| `two_factor_enabled` | boolean | yes |  |  |
| `version` | string | yes |  | The running build. dev when none was stamped. |

### MeKey

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) | no |  | When the key stops working. Absent when it never does. |
| `id` | string | yes |  |  |
| `may_mint_keys` | boolean | yes |  | Whether this key may make keys for other accounts. |
| `may_sign_in` | boolean | yes |  | Whether this key may make a login link for its own account. |
| `name` | string | yes |  |  |
| `role` | string | yes | one of `admin`, `user`, `viewer` | The key's own role. The role it acts with is the lower of this and the account's. |

### Member

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `id` | integer | yes |  |  |

### NewAPIKey

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `created_by` | integer | no |  | The admin who made this key for its owner. Absent if the owner made it. |
| `created_by_name` | string | no |  |  |
| `credential` | string | yes |  | Shown in this response only, and never recoverable. |
| `display_name` | string | no |  | The key's owner. On the admin list only. |
| `expired` | boolean | yes |  |  |
| `expires_at` | string (date-time) | no |  |  |
| `id` | string | yes |  |  |
| `last_used_at` | string (date-time) | no |  |  |
| `live` | boolean | yes |  |  |
| `may_mint_keys` | boolean | yes |  | Whether this key may make keys for other accounts. Only the owner switches it on. |
| `may_sign_in` | boolean | yes |  | Whether this key may make a login link for its own account. |
| `minted_by_key` | string | yes |  | The key that made this one, or empty. Revoking that key revokes this one. |
| `name` | string | yes |  |  |
| `revoked` | boolean | yes |  |  |
| `revoked_at` | string (date-time) | no |  |  |
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |
| `user_id` | integer | yes |  |  |

### PortalAccount

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `id` | integer | yes |  |  |
| `keys` | array of [`APIKey`](#apikey) | yes |  | Its live keys, newest first. |

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
| `api_keys` | integer | yes |  |  |
| `login_links` | integer | yes |  |  |
| `sessions` | integer | yes |  |  |

### RotatedKey

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  | The key's new credential, shown in this response only. The old one stopped working. |

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
