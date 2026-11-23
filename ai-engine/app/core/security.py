import hmac
from fastapi import Header, HTTPException
from app.core.config import settings

async def require_service_token(authorization: str | None = Header(default=None)) -> None:
    expected = settings.service_token
    scheme, separator, supplied = (authorization or "").partition(" ")
    if (
        not expected
        or not separator
        or scheme.casefold() != "bearer"
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Valid service credentials are required"})
