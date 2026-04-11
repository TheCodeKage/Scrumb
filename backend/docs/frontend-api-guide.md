# Scrumb Frontend API Integration Guide

This guide is for frontend developers integrating with the current backend implementation.

Source of truth used for this guide:
- `backend/urls.py`
- `backend/settings.py`
- `Users/routers.py`, `Users/views.py`, `Users/serializers.py`
- `projects/routers.py`, `projects/views.py`, `projects/serializers.py`
- `api_responses.py`
- `tests/users/*.http`, `tests/projects/*.http`

---

## 1) Integration Sequence (Recommended Order)

1. Configure `BASE_URL` and auth token handling.
2. Signup user via auth API.
3. Complete email verification flow (frontend link -> backend verify call).
4. Login and persist JWT access/refresh tokens.
5. Fetch current user profile.
6. Team lifecycle:
   - create/list teams
   - invite members
   - accept/decline invites
   - send/approve join requests
7. Project lifecycle:
   - create project
   - fetch interview questions (if any)
   - answer all questions
   - generate plan
   - read/update tasks
8. Analytics and panic endpoints for planning control.

---

## 2) Base URL and Authentication

### Base URL
Use your deployed API host, for example:
- `https://api.scrumb.in`
- local dev example: `http://127.0.0.1:8000`

### Auth scheme
Backend uses JWT bearer auth (`rest_framework_simplejwt`):
- Header: `Authorization: Bearer <access_token>`

### Pagination
Global DRF pagination is enabled (`PAGE_SIZE=15`), so list endpoints commonly return:

```json
{
  "count": 0,
  "next": null,
  "previous": null,
  "results": []
}
```

---

## 3) Response Formats You Must Handle

The API currently has **two response shapes**.

### A) Standardized custom-action envelope
Used by many custom actions in `Users/views.py` and `projects/views.py`:

```json
{
  "success": true,
  "message": "Human readable message",
  "data": {},
  "errors": []
}
```

Error example:

```json
{
  "success": false,
  "message": "Validation message",
  "data": null,
  "errors": [
    {"field": "username", "detail": "Username is required"}
  ]
}
```

### B) Default DRF serializer shape
Used by standard CRUD list/retrieve/create/update actions (for example `GET /project/`, `POST /project/`).

Frontend should branch by checking whether `success` exists.

---

## 4) Auth and Account Endpoints (Sequence)

Auth routes are mounted under `api/auth/` via dj-rest-auth include in `backend/urls.py`.

### 4.1 Signup
`POST /api/auth/registration/`

Request:

```json
{
  "email": "user@example.com",
  "username": "user1",
  "password1": "StrongPassword",
  "password2": "StrongPassword"
}
```

### 4.2 Email confirmation flow
Email confirmation URL is customized by `Users/adapter.py` to:

```
<FRONTEND_URL>/verify-email.html?key=<email_confirmation_key>
```

Frontend sequence:
1. Read `key` query param from your verify page.
2. POST key to the backend email verify endpoint from dj-rest-auth registration (commonly `/api/auth/registration/verify-email/`).

Request shape typically:

```json
{
  "key": "<email_confirmation_key>"
}
```

### 4.3 Login
`POST /api/auth/login/`

Request:

```json
{
  "username": "user1",
  "password": "StrongPassword"
}
```

Observed in test scripts (`tests/users/auth.http`): response includes `access` token.

### 4.4 Current user
`GET /api/auth/user/`

Header:

```
Authorization: Bearer <access_token>
```

### 4.5 Password reset
Configured via custom serializer (`Users/serializers.py`) and confirm route in `backend/urls.py`:
- confirm path: `/api/auth/password-reset-confirm/<uidb64>/<token>`

---

## 5) Users Domain APIs

Router prefix: `/users/`

### 5.1 Developer endpoints
From `Users/routers.py`:
- `GET /users/developer/`
- `GET /users/developer/{id}/`
- `POST /users/developer/{id}/add_skill/` (custom envelope)
- `POST /users/developer/{id}/remove_skill/` (custom envelope)
- `GET /users/developer/{id}/get_skills/` (custom envelope)

`add_skill` / `remove_skill` request:

```json
{
  "skill": "Python"
}
```

### 5.2 Team endpoints
- `GET /users/team/` (supports `?show_all=true`)
- `POST /users/team/`
- `GET /users/team/{id}/`
- `PATCH /users/team/{id}/`
- `DELETE /users/team/{id}/`
- `POST /users/team/{id}/invite/` (custom envelope)
- `POST /users/team/{id}/join_request/` (custom envelope)
- `GET /users/team/{id}/join_requests/` (custom envelope)
- `POST /users/team/{id}/approve_join_request/` (custom envelope)

`invite` request:

```json
{
  "username": "target_user"
}
```

`approve_join_request` request:

```json
{
  "invitation_id": 123
}
```

### 5.3 Invitation endpoints
- `GET /users/invite/`
- `GET /users/invite/{id}/`
- `POST /users/invite/{id}/accept/` (custom envelope)
- `POST /users/invite/{id}/decline/` (custom envelope)

---

## 6) Projects Domain APIs

Top-level routes from `projects/routers.py`:
- `/project/`
- `/project/plan/`
- `/project/panic/`
- `/project/analytics/`
- `/task/`
- `/question/`

### 6.1 Project CRUD (`/project/`)
- `GET /project/`
- `POST /project/`
- `GET /project/{id}/`
- `PATCH /project/{id}/`
- `DELETE /project/{id}/`

Create request:

```json
{
  "name": "Project Name",
  "team_id": 1,
  "description": "Long detailed description",
  "guarantee_date": "2026-06-30"
}
```

Create/CRUD responses are default DRF serializer responses.

### 6.2 Planning flow (`/project/plan/`)

#### Generate plan
`POST /project/plan/{project_id}/generate_plan/`

- Fails if plan already exists
- Fails if interview questions are not fully answered
- Returns custom envelope

#### Answer all questions
`POST /project/plan/{project_id}/answer_all/`

Request:

```json
{
  "answers": [
    {"question_id": 10, "selected_option_id": 100},
    {"question_id": 11, "selected_option_id": 105}
  ]
}
```

#### Interview state
`GET /project/plan/{project_id}/interview/`

Envelope `data.phase` values:
- `AUDITING` (questions still being generated)
- `INTERVIEWING` (includes `questions` array)

### 6.3 Analytics flow (`/project/analytics/`)
- `GET /project/analytics/{project_id}/health/`
- `GET /project/analytics/{project_id}/stalled_tasks/`
- `GET /project/analytics/{project_id}/roast/`

All three return custom envelope.

### 6.4 Panic flow (`/project/panic/`)
- `POST /project/panic/{project_id}/panic_previews/`
- `POST /project/panic/{project_id}/panic_mode/`

Both return custom envelope.

### 6.5 Task flow (`/task/`)
- `GET /task/`
- `GET /task/{id}/`
- `PATCH /task/{id}/`
- `DELETE /task/{id}/`

Notes:
- Task status choices: `to-do`, `doing`, `done`, `archived`
- Backend blocks setting `done` if sub-tasks or dependencies are unfinished.
- Task endpoints are default DRF response format.

### 6.6 Question flow (`/question/`)
- `GET /question/` (supports `?project=<id>`)
- `GET /question/{id}/`
- `POST /question/{id}/select/` (custom envelope)

`select` request:

```json
{
  "selected_option_id": 100
}
```

---

## 7) End-to-End Frontend Journeys

### Journey A: New user onboarding
1. Signup via `/api/auth/registration/`.
2. User receives email with frontend verify URL (`verify-email.html?key=...`).
3. Verify page posts key to backend verification endpoint.
4. Login via `/api/auth/login/`.
5. Store `access` token and call `/api/auth/user/`.

### Journey B: Team invite flow
1. Leader creates team: `POST /users/team/`.
2. Leader invites user: `POST /users/team/{id}/invite/`.
3. Invited user lists invites: `GET /users/invite/`.
4. Invited user accepts: `POST /users/invite/{invite_id}/accept/`.

### Journey C: Join request flow
1. Developer sends request: `POST /users/team/{id}/join_request/`.
2. Leader checks requests: `GET /users/team/{id}/join_requests/`.
3. Leader approves: `POST /users/team/{id}/approve_join_request/`.

### Journey D: Project planning flow
1. Leader creates project: `POST /project/`.
2. Poll `GET /project/plan/{id}/interview/`.
3. If phase is `INTERVIEWING`, collect answers.
4. Submit answers: `POST /project/plan/{id}/answer_all/`.
5. Generate tasks: `POST /project/plan/{id}/generate_plan/`.
6. Render tasks from `GET /project/{id}/` or `/task/`.

---

## 8) Frontend Error Handling Rules

1. If response contains `success`, parse custom envelope:
   - `success == false`: show `message`, inspect `errors[]`.
2. Else parse DRF default shape:
   - field errors: `{ "field_name": ["..."] }`
   - generic errors: `{ "detail": "..." }`
3. For 401, trigger re-auth/refresh flow.
4. For 403, show permission-specific message.
5. For 404 on custom actions, treat as stale route/id and refresh data.

---

## 9) Minimal Frontend Contract Types

Suggested TypeScript interfaces:

```ts
export interface ApiEnvelope<T = unknown> {
  success: boolean;
  message: string;
  data: T | null | Record<string, never>;
  errors: Array<{ field?: string; detail: string }>;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
```

---

## 10) Health Check

`GET /healthz`

Returns:

```json
{
  "status": "healthy",
  "service": "scrumb-backend"
}
```

---

## 11) Practical Notes for Frontend Team

- Custom action endpoints are now normalized, but CRUD endpoints still use default DRF shapes.
- Build API utilities that support both formats until backend fully normalizes all endpoints.
- Use centralized request/response interceptors for JWT header injection and 401 handling.
- For list endpoints, always support pagination (`results`, `count`, `next`, `previous`).

