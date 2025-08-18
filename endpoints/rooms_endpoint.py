from fastapi import APIRouter, HTTPException

from models.room_models import CreateRoomRequest, JoinRoomRequest, MediaStatusUpdate
import json

from repos.file_storage_manager_repo import FileStorageManager
from service.connection_manager_service import ConnectionManager

router = APIRouter(prefix="/api/rooms", tags=["Rooms"])

storage = FileStorageManager()
manager = ConnectionManager(storage)


@router.post("")
async def create_room(request: CreateRoomRequest):
    room_id = storage.create_room(request.max_participants)
    return {"room_id": room_id, "join_url": f"/room/{room_id}", "max_participants": request.max_participants}


@router.get("/{room_id}")
async def get_room_info(room_id: str):
    room = storage.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    participants = storage.get_room_participants(room_id)
    return {
        "room_id": room_id,
        "participants": participants,
        "participant_count": len(participants),
        "max_participants": room["max_participants"],
        "created_at": room["created_at"]
    }


@router.post("/{room_id}/join")
async def join_room_api(room_id: str, request: JoinRoomRequest):
    return storage.join_room(room_id, request.display_name)


@router.patch("/{room_id}/users/{user_id}/media")
async def update_media_status(room_id: str, user_id: str, request: MediaStatusUpdate):
    storage.update_media_status(room_id, user_id, request.audio_enabled, request.video_enabled)
    message = json.dumps({"type": "user-media-changed", "user_id": user_id,
                          "audio_enabled": request.audio_enabled, "video_enabled": request.video_enabled})
    await manager.broadcast_to_room(message, room_id, exclude_user=user_id)
    return {"message": "Media status updated"}


@router.delete("/{room_id}")
async def end_room(room_id: str):
    if room_id in manager.active_connections:
        end_message = json.dumps({"type": "room-ended", "message": "Room has been ended by host"})
        await manager.broadcast_to_room(end_message, room_id)
        connections = list(manager.active_connections[room_id].values())
        for connection in connections:
            try:
                await connection.close()
            except:
                pass
        del manager.active_connections[room_id]
    return {"message": "Room ended successfully"}
