from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import json, logging

from repos.file_storage_manager_repo import FileStorageManager
from service.connection_manager_service import ConnectionManager

router = APIRouter(tags=["WebSocket"])

storage = FileStorageManager()
manager = ConnectionManager(storage)
logger = logging.getLogger(__name__)
# add at top with other imports
from service.recorder_service import RecorderManager

recorder = RecorderManager(base_dir="recordings")



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

                # Original WebRTC handling + Screen sharing WebRTC
                if message_type in ["webrtc-offer", "webrtc-answer", "ice-candidate",
                                    "screen-share-offer", "screen-share-answer", "screen-share-ice-candidate"]:
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

                # Screen sharing status updates
                elif message_type in ["screen-share-started", "screen-share-stopped"]:
                    is_sharing = message_type == "screen-share-started"
                    await manager.broadcast_to_room(
                        json.dumps({"type": "user-screen-share-changed", "user_id": user_id,
                                    "is_sharing": is_sharing}),
                        room_id, exclude_user=user_id
                    )
                elif message_type == "recorder-offer":
                    # { type:"recorder-offer", sdp:"...", sdpType:"offer" }
                    sdp = message.get("sdp")
                    sdp_type = message.get("sdpType", "offer")
                    answer = await recorder.start_or_renegotiate(room_id, user_id, sdp, sdp_type)
                    await websocket.send_text(json.dumps({
                        "type": "recorder-answer",
                        "sdp": answer["sdp"],
                        "sdpType": answer["type"]
                    }))

                elif message_type == "recorder-ice-candidate":
                    # { type:"recorder-ice-candidate", candidate: {candidate, sdpMid, sdpMLineIndex} | null }
                    await recorder.add_ice(room_id, user_id, message.get("candidate"))

                elif message_type == "recorder-stop":
                    await recorder.stop(room_id, user_id)
                    await websocket.send_text(json.dumps({"type": "recorder-stopped"}))

                else:
                    message["from_user"] = user_id
                    await manager.broadcast_to_room(json.dumps(message), room_id, exclude_user=user_id)
            except:
                await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON format"}))

    except WebSocketDisconnect:
        pass
    finally:
        try:
            await recorder.stop(room_id, user_id)
        except Exception:
            pass
        await manager.disconnect(websocket)