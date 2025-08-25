from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException

from repos.file_storage_manager_repo import FileStorageManager
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Enhanced connection manager with user tracking"""

    def __init__(self, storage: FileStorageManager):
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}  # {room_id: {user_id: websocket}}
        self.user_to_room: Dict[WebSocket, tuple] = {}  # {websocket: (room_id, user_id)}
        self.storage = storage

    async def connect(self, websocket: WebSocket, room_id: str, user_id: str, display_name: str):
        """Connect user to room"""
        try:
            await websocket.accept()
            logger.info(f"WebSocket accepted for user {user_id} in room {room_id}")  # ADD LOGGING
        except Exception as e:
            logger.error(f"Failed to accept WebSocket for user {user_id}: {e}")  # ADD ERROR LOGGING
            raise

        # Initialize room if it doesn't exist in active connections
        if room_id not in self.active_connections:
            self.active_connections[room_id] = {}

        # Store connection
        self.active_connections[room_id][user_id] = websocket
        self.user_to_room[websocket] = (room_id, user_id)

        # Get existing users in room (exclude current user)
        existing_users = []
        participants = self.storage.get_room_participants(room_id)
        for participant in participants:
            if participant["user_id"] != user_id and participant["user_id"] in self.active_connections[room_id]:
                existing_users.append({
                    "user_id": participant["user_id"],
                    "display_name": participant["display_name"],
                    "audio_enabled": participant["is_audio_enabled"],
                    "video_enabled": participant["is_video_enabled"]
                })

        # Send room-joined message to new user
        await websocket.send_text(json.dumps({
            "type": "room-joined",
            "user_id": user_id,
            "room_id": room_id,
            "existing_users": existing_users,
            "is_initiator": len(existing_users) == 0
        }))

        # Notify existing users about new user
        if existing_users:
            new_user_message = json.dumps({
                "type": "new-user-joined",
                "new_user": {
                    "user_id": user_id,
                    "display_name": display_name,
                    "audio_enabled": True,
                    "video_enabled": True
                }
            })
            await self.broadcast_to_room(new_user_message, room_id, exclude_user=user_id)

        logger.info(
            f"User {user_id} connected to room {room_id}. Room has {len(self.active_connections[room_id])} users")
        return len(existing_users)

    async def disconnect(self, websocket: WebSocket):
        """Disconnect user from room"""
        if websocket in self.user_to_room:
            room_id, user_id = self.user_to_room[websocket]

            # Remove from active connections
            if room_id in self.active_connections and user_id in self.active_connections[room_id]:
                del self.active_connections[room_id][user_id]

            del self.user_to_room[websocket]

            # Notify other users
            user_left_message = json.dumps({
                "type": "user-left",
                "user_id": user_id
            })
            await self.broadcast_to_room(user_left_message, room_id, exclude_user=user_id)

            # Update storage
            self.storage.leave_room(room_id, user_id)

            # Clean up empty room
            if room_id in self.active_connections and len(self.active_connections[room_id]) == 0:
                del self.active_connections[room_id]

            logger.info(f"User {user_id} disconnected from room {room_id}")

    async def broadcast_to_room(self, message: str, room_id: str, exclude_user: str = None):
        """Broadcast message to all users in room except excluded user"""
        if room_id in self.active_connections:
            disconnected = []
            for user_id, connection in self.active_connections[room_id].items():
                if user_id != exclude_user:
                    try:
                        await connection.send_text(message)
                    except Exception as e:
                        logger.error(f"Error sending message to user {user_id}: {e}")
                        disconnected.append(user_id)

            # Clean up disconnected users
            for user_id in disconnected:
                if user_id in self.active_connections[room_id]:
                    del self.active_connections[room_id][user_id]

    async def send_to_user(self, message: str, room_id: str, target_user: str):
        """Send message to specific user in room"""
        if room_id in self.active_connections and target_user in self.active_connections[room_id]:
            try:
                await self.active_connections[room_id][target_user].send_text(message)
            except Exception as e:
                logger.error(f"Error sending message to user {target_user}: {e}")
                # Clean up disconnected user
                del self.active_connections[room_id][target_user]
