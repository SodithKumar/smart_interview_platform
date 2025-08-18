from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import json, logging

from repos.file_storage_manager_repo import FileStorageManager
from service.connection_manager_service import ConnectionManager

router = APIRouter(tags=["WebSocket"])

storage = FileStorageManager()
manager = ConnectionManager(storage)
logger = logging.getLogger(__name__)


@router.websocket("/ws/{room_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, user_id: str):
    try:
        participants = storage.get_room_participants(room_id)
        user_info = next((p for p in participants if p["user_id"] == user_id), None)
        if not user_info:
            await websocket.close(code=4004, reason="User not found in room")
            return

        await manager.connect(websocket, room_id, user_id, user_info["display_name"])

        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                message_type = message.get("type", "unknown")

                if message_type in ["webrtc-offer", "webrtc-answer", "ice-candidate"]:
                    target_user = message.get("to_user")
                    if target_user:
                        message["from_user"] = user_id
                        await manager.send_to_user(json.dumps(message), room_id, target_user)

                elif message_type == "media-toggle":
                    audio_enabled = message.get("audio_enabled", True)
                    video_enabled = message.get("video_enabled", True)
                    storage.update_media_status(room_id, user_id, audio_enabled, video_enabled)
                    await manager.broadcast_to_room(
                        json.dumps({"type": "user-media-changed", "user_id": user_id,
                                    "audio_enabled": audio_enabled, "video_enabled": video_enabled}),
                        room_id, exclude_user=user_id
                    )
                else:
                    message["from_user"] = user_id
                    await manager.broadcast_to_room(json.dumps(message), room_id, exclude_user=user_id)
            except:
                await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON format"}))

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
