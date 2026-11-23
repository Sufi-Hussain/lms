# AI STEM Teaching Engine

Standalone FastAPI service for the LMS tutoring workflow. It provides versioned session, profile, message, answer, hint, and resume endpoints; a persisted interaction history; configurable OpenAI/Gemini-compatible generation; and a local mock provider for integration testing. It does not modify the frontend build.

## Run locally

```sh
cd ai-engine
cp .env.example .env
# Set SERVICE_TOKEN to a random secret. Keep it private.
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8100
```

Set `LLM_PROVIDER=mock` to run without model credentials, `openai` with `OPENAI_API_KEY`, or `gemini` with `GEMINI_API_KEY`. `DATABASE_URL` defaults to SQLite for local development; use a PostgreSQL URL for shared deployments. Health: `GET /api/v1/health`. OpenAPI: `/docs`.

## Docker Compose

From the `ai-engine/` directory, copy `.env.example` to `.env`, set a strong `SERVICE_TOKEN`, then run `docker compose -f docker-compose.ai-engine.yml up -d --build`. Set `FRAPPE_DOCKER_NETWORK` in the Compose environment to the existing network name (for this repo's `name: lms` compose project that is normally `lms_default`; verify with `docker network ls` for your deployment). The service attaches to that external network and resolves Frappe at `http://frappe:8000`; it has no published host port. This separate compose file does not modify existing Frappe services.

## API contract

All `/api/v1` endpoints other than health require `Authorization: Bearer <SERVICE_TOKEN>`. This is service-to-service authentication; do not expose the engine directly to browsers or treat this static token as student authentication. The trusted LMS backend must authenticate the learner, derive `school_id`, `student_id`, and course access from its own session, and call this service server-side. Scope every session lookup by the server-derived school. Keep the engine on a private network, add an edge rate limit, and rotate the token.

- `POST /api/v1/sessions`: `{student_id, school_id, course_id, subject, chapter, topic, language?}`. With `FRAPPE_URL` configured, retrieves server-owned curriculum from `lms.ai_integration.get_tutor_context`.
- `GET /api/v1/sessions/{id}?school_id=...`: resume-safe persisted session state.
- `POST /api/v1/sessions/{id}/message?school_id=...`: `{text}`.
- `POST /api/v1/sessions/{id}/answer?school_id=...`: `{question_id, answer}`; question IDs prevent stale answer submissions.
- `POST /api/v1/sessions/{id}/hint?school_id=...` and `/resume?school_id=...`.
- `GET /api/v1/students/{id}/learning-profile?school_id=...`: proxies the LMS-owned profile endpoint.

The engine calls these Frappe whitelisted methods using a dedicated least-privilege Frappe API user: `lms.ai_integration.get_tutor_context`, `lms.ai_integration.save_tutor_event`, and `lms.ai_integration.get_learning_profile`. They are an explicit integration contract, not present in upstream LMS by default. Implement them in the LMS backend using the actual enrollment, tenant, lesson, quiz, and resource doctypes for your deployment. Authenticate the caller as a dedicated integration user, validate its roles and every tenant/student/course relationship on every request, and return only curriculum and embedding-approved media. Never accept a school or student identity as authorization merely because it appears in a request body. A deployment's exact Doctype fields and student-to-school rules must be confirmed before writing that adapter; this engine does not guess them or change LMS authorization rules.

### Frappe payload contract

`get_tutor_context` accepts the session creation fields and returns a `message` object with `learning_objective` (string), `concept_id` (string), `expected_answer` (string), and optionally `resources` (array). Resource entries may contain `resource_id`, `resource_type`, `youtube_video_id`, `subject`, `topic`, `start_time`, and `embedding_allowed`. Only approved YouTube resources are passed to the client. `save_tutor_event` accepts `{school_id, student_id, session_id, event}`; have Frappe apply its retention and data-minimization policy. `get_learning_profile` accepts the authenticated student's ID and school ID and returns a server-authorized profile. Keep PII, provider credentials, and raw learner identifiers out of model prompts and application logs where possible.

## Structure

`app/api/v1` owns HTTP routes, `app/services/orchestrator.py` handles lesson/session state, `app/ai/providers` adapts model providers, `app/integrations/frappe_client.py` owns LMS calls, and `app/assessment` / `app/teaching` / `app/resources` contain focused learning behavior. SQLite/Postgres stores resumable session history. Frappe remains authoritative for learner identity, enrollment, curriculum, approved resources, and learning-profile data.

## Important implementation notes

The included short-answer evaluator is intentionally conservative exact-match scaffolding; replace it with teacher-reviewed, curriculum-specific assessment logic before using it for grades or mastery decisions. The mock provider is for development only. Model output must be reviewed for age appropriateness and factuality. Add migrations and production database backups before deploying schema changes. Validate Frappe adapter permissions and the LMS frontend's server-side authentication before enabling student traffic.
