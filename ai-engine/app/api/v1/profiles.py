import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.rate_limit import enforce_rate_limit
from app.core.security import require_service_token
from app.integrations.frappe_client import FrappeClient
from app.models.schemas import LearningProfile


router = APIRouter(
    dependencies=[Depends(require_service_token), Depends(enforce_rate_limit)],
    tags=["learning profiles"],
)
frappe_client = FrappeClient()


@router.get("/students/{student_id}/learning-profile", response_model=LearningProfile)
async def get_learning_profile(
    student_id: str,
    school_id: str = Query(min_length=1, max_length=140),
):
    try:
        profile = await frappe_client.get_learning_profile(student_id, school_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found", "message": "Learning profile not found"}) from exc
        raise HTTPException(status_code=502, detail={"code": "lms_profile_unavailable", "message": "The LMS learning profile is unavailable"}) from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail={"code": "lms_profile_unavailable", "message": "The LMS learning profile is unavailable"}) from exc

    return LearningProfile(
        student_id=student_id,
        school_id=school_id,
        concepts=profile.get("concepts", []),
        recommended_next_lesson=profile.get("recommended_next_lesson"),
    )
