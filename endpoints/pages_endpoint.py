from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter(tags=["Pages"])

ROOT = Path(__file__).resolve().parents[1]  # points to app/
STATIC_DIR = ROOT / "static"


@router.get("/", include_in_schema=False)
def get_join_page():
    return FileResponse(str(STATIC_DIR / "room.html"))


@router.get("/join", include_in_schema=False)
def get_join_page_explicit():
    return FileResponse(str(STATIC_DIR / "room.html"))


@router.get("/room/{room_id}", include_in_schema=False)
def get_room_interface(room_id: str):
    return FileResponse(str(STATIC_DIR / "index.html"))
