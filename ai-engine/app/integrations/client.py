from app.core.config import settings
from app.integrations.frappe_client import FrappeClient
from app.integrations.mock_frappe_client import MockFrappeClient


def create_frappe_client():
    if settings.frappe_mode == "mock":
        return MockFrappeClient()
    if settings.frappe_mode == "live":
        return FrappeClient()
    raise ValueError("FRAPPE_MODE must be mock or live")


frappe_client = create_frappe_client()
