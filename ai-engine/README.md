# AI STEM Teaching Engine

A standalone FastAPI tutoring service for the existing Frappe LMS app in this repository. The service owns short-lived orchestration state; Frappe remains authoritative for LMS users, school/course access, curriculum, approved resources, and learning profiles. Student-facing clients must call Frappe, which authenticates the learner and calls this service server-to-server.

## Verified LMS assumptions

This repository contains the upstream `LMS Enrollment` DocType with `member`, `course`, and `member_type` fields, and `Course Chapter` linked to `LMS Course`. It does not contain the proposed school, curriculum-concept, resource, tutor-session, or learner-profile DocTypes. Their definitions are in `frappe_integration/proposed_doctypes.json`; review and install them in the Frappe app before enabling the sample adapter. The sample bridge adds `lms/lms/ai_integration.py` and relies on a trusted `AI Student School Access` mapping for each student-school-course enrollment. Populate that mapping from your authoritative school membership data; do not infer school membership from a request.

## Local development

```sh
cd ai-engine
cp .env.example .env
# Set SERVICE_TOKEN and Frappe credentials; keep .env private.
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

The default `LLM_PROVIDER=mock` requires no model key and is for development/testing only. Set `LLM_PROVIDER=openai` with `OPENAI_API_KEY`, or `LLM_PROVIDER=gemini` with `GEMINI_API_KEY`. Provider/model names and request timeouts are environment-configurable. SQLite is for local/single-instance development; configure PostgreSQL for a shared deployment. Health is `GET /api/v1/health`; OpenAPI docs are available at `/docs`. The docs route is not separately authenticated, so keep the service and documentation on a private network.

## Docker Compose

From `ai-engine/`, copy `.env.example` to `.env`; configure a long random `SERVICE_TOKEN`, the dedicated Frappe API key/secret, and the existing Frappe Compose network. For this repository's Compose project name `lms`, the default network is normally `lms_default`; verify the actual network name in your deployment. Then run:

```sh
docker compose -f docker-compose.ai-engine.yml up -d --build
```

The service binds to internal port `8001` and publishes no host port. It joins the existing network and calls `http://frappe:8000`; it does not create duplicate MariaDB or Redis services. The SQLite data volume is intended only for a single instance. Use a managed/shared PostgreSQL database before running multiple replicas.

## Frappe setup

1. Create the proposed DocTypes from `frappe_integration/proposed_doctypes.json`, reviewing their permissions and retention policy first.
2. Create the dedicated `AI Engine Service` role and integration user. Grant only the roles/permissions required by the custom bridge; generate that user's Frappe API key and secret.
3. Copy `frappe_integration/ai_integration.py` to `lms/lms/ai_integration.py` (or the equivalent module in your Frappe app), run the app's migration/reload steps, and verify the whitelisted bridge methods from the private Docker network.
4. Populate `AI Student School Access` from authoritative school membership data, create enabled `AI Curriculum Concept` records linked to real `LMS Course` and `Course Chapter` records, and curate `AI Educational Resource` rows. Only set `embedding_allowed` for resources approved for display.
5. Configure `FRAPPE_URL`, `FRAPPE_API_KEY`, and `FRAPPE_API_SECRET` in the engine's private environment. Store matching `ai_engine_url` and `ai_engine_service_token` values in Frappe's private site configuration. Never add credentials to frontend code or commit `.env` / `site_config.json`.
6. The sample authenticated Frappe methods `start_tutor_lesson`, `submit_tutor_answer`, `send_tutor_message`, `request_tutor_hint`, `resume_tutor_lesson`, `get_student_tutor_session`, and `get_student_learning_profile` derive the student from `frappe.session.user` and check the supplied course/school against both the trusted school mapping and existing `LMS Enrollment`. Use these methods from the Frappe frontend with `frappe.call`; do not proxy client-supplied student IDs or trust a school ID without server-side validation.

The bridge validates `LMS Enrollment` and the custom school-access mapping on lesson start and every session/profile access. The engine also rechecks Frappe authorization before actions on locally cached sessions. Session snapshots and sanitized conversation history are private; the custom session DocType must remain restricted to administrators and the integration service.

The engine-to-LMS adapter calls `get_tutor_context`, `authorize_tutor_student`, `save_tutor_session`, `get_tutor_session`, `save_tutor_event`, and `get_learning_profile` using the dedicated integration user. These whitelisted methods require the `AI Engine Service` role, check `LMS Enrollment` plus the school-access mapping, and return only published curriculum and approved resources. The Frappe methods invoked by the student-facing app derive the learner from the authenticated Frappe session; service credentials stay in Frappe's private site config and the engine's private environment.

## API contract

Except for health, endpoints require `Authorization: Bearer <SERVICE_TOKEN>`. This credential authenticates the Frappe service, not a student, and must never be sent to browsers. Use the backend-derived `school_id` and `student_id` on session read/action routes.

- `POST /api/v1/sessions` — `{student_id, school_id, course_id, subject, chapter, topic, language?}`; fetches the published learning objective and approved resources from Frappe.
- `GET /api/v1/sessions/{session_id}?school_id=...&student_id=...` — returns a scoped persisted session.
- `POST /api/v1/sessions/{session_id}/message?school_id=...&student_id=...` — `{text}`.
- `POST /api/v1/sessions/{session_id}/answer?school_id=...&student_id=...` — `{question_id, answer}`; stale question IDs are rejected.
- `POST /api/v1/sessions/{session_id}/hint?school_id=...&student_id=...` and `/resume` — get a hint or continue a persisted lesson.
- `GET /api/v1/students/{student_id}/learning-profile?school_id=...` — returns scoped concept-level progress and a next-concept recommendation.
- `GET /api/v1/health` — liveness check; does not reveal configuration.

Responses use validated Pydantic schemas and include the teaching state, localized teacher message, optional curated visual resource, interaction type/options, mastery summary, next action, and LMS sync status. Frappe synchronization uses a SQL outbox so brief LMS outages do not discard local session/progress writes; responses report `sync_status: pending` until retried.

## Architecture and limits

`app/api/v1` handles authenticated HTTP routes, `app/services/orchestrator.py` runs the short interaction flow, `app/ai/providers` provides mock/OpenAI/Gemini adapters, `app/integrations/frappe_client.py` owns server-to-server calls, and `app/assessment`, `app/teaching`, and `app/resources` contain focused logic. Contact details are redacted before student messages reach a model or persistent history. Model outputs are validated; numerical and choice answers use deterministic grading where possible. Approved media are returned by catalogue ID and video ID only; arbitrary executable HTML is never generated.

This is a deployable integration foundation, not a substitute for tenant-specific review. Before real student traffic, test the Frappe role and school mapping in your deployment, provision an encrypted/backup-backed PostgreSQL database, review school consent and retention rules, and have educators validate generated lessons and grading. The mock provider and local SQLite configuration are not production assessment settings; do not use model-generated grades for high-stakes decisions without a teacher-reviewed rubric and validation process.
