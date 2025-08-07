from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Set
import asyncio
from threading import Lock

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WebRTC Video Call Server", version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")


# Pydantic models for API requests
class CreateRoomRequest(BaseModel):
    max_participants: int = 6


class JoinRoomRequest(BaseModel):
    display_name: str


class MediaStatusUpdate(BaseModel):
    audio_enabled: bool
    video_enabled: bool


class FileStorageManager:
    """File-based storage manager for rooms and participants"""

    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        self.rooms_file = f"{data_dir}/rooms.json"
        self.participants_file = f"{data_dir}/participants.json"
        self.file_lock = Lock()
        self._ensure_data_dir()

    def _ensure_data_dir(self):
        """Create data directory and initialize files if they don't exist"""
        os.makedirs(self.data_dir, exist_ok=True)

        if not os.path.exists(self.rooms_file):
            self._write_json(self.rooms_file, {})

        if not os.path.exists(self.participants_file):
            self._write_json(self.participants_file, {})

    def _read_json(self, filepath: str) -> dict:
        """Safely read JSON file"""
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_json(self, filepath: str, data: dict):
        """Safely write JSON file"""
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def create_room(self, max_participants: int = 6) -> str:
        """Create new room and return room_id"""
        room_id = str(uuid.uuid4())[:8]

        with self.file_lock:
            rooms = self._read_json(self.rooms_file)
            rooms[room_id] = {
                "room_id": room_id,
                "created_at": datetime.now().isoformat(),
                "max_participants": max_participants,
                "is_active": True,
                "current_participants": 0
            }
            self._write_json(self.rooms_file, rooms)

            # Initialize participants for this room
            participants = self._read_json(self.participants_file)
            participants[room_id] = {}
            self._write_json(self.participants_file, participants)

        logger.info(f"Created room {room_id} with max {max_participants} participants")
        return room_id

    def get_room(self, room_id: str) -> Optional[dict]:
        """Get room information"""
        rooms = self._read_json(self.rooms_file)
        return rooms.get(room_id)

    def join_room(self, room_id: str, display_name: str) -> dict:
        """Add user to room, return user info"""
        user_id = str(uuid.uuid4())[:8]

        with self.file_lock:
            # Check if room exists and has space
            rooms = self._read_json(self.rooms_file)
            if room_id not in rooms:
                raise HTTPException(status_code=404, detail="Room not found")

            room = rooms[room_id]
            if room["current_participants"] >= room["max_participants"]:
                raise HTTPException(status_code=400, detail="Room is full")

            # Add user to participants
            participants = self._read_json(self.participants_file)
            if room_id not in participants:
                participants[room_id] = {}

            user_info = {
                "user_id": user_id,
                "display_name": display_name,
                "joined_at": datetime.now().isoformat(),
                "is_audio_enabled": True,
                "is_video_enabled": True,
                "is_connected": True
            }

            participants[room_id][user_id] = user_info
            self._write_json(self.participants_file, participants)

            # Update room participant count
            rooms[room_id]["current_participants"] += 1
            self._write_json(self.rooms_file, rooms)

        logger.info(f"User {user_id} ({display_name}) joined room {room_id}")
        return user_info

    def leave_room(self, room_id: str, user_id: str):
        """Remove user from room"""
        with self.file_lock:
            participants = self._read_json(self.participants_file)
            rooms = self._read_json(self.rooms_file)

            # Remove user from participants
            if room_id in participants and user_id in participants[room_id]:
                del participants[room_id][user_id]
                self._write_json(self.participants_file, participants)

                # Update room participant count
                if room_id in rooms:
                    rooms[room_id]["current_participants"] = max(0, rooms[room_id]["current_participants"] - 1)

                    # Clean up empty rooms
                    if rooms[room_id]["current_participants"] == 0:
                        del rooms[room_id]
                        if room_id in participants:
                            del participants[room_id]

                    self._write_json(self.rooms_file, rooms)
                    self._write_json(self.participants_file, participants)

        logger.info(f"User {user_id} left room {room_id}")

    def get_room_participants(self, room_id: str) -> List[dict]:
        """Get all users in a room"""
        participants = self._read_json(self.participants_file)
        if room_id not in participants:
            return []
        return list(participants[room_id].values())

    def update_media_status(self, room_id: str, user_id: str, audio_enabled: bool, video_enabled: bool):
        """Update user's audio/video status"""
        with self.file_lock:
            participants = self._read_json(self.participants_file)
            if room_id in participants and user_id in participants[room_id]:
                participants[room_id][user_id]["is_audio_enabled"] = audio_enabled
                participants[room_id][user_id]["is_video_enabled"] = video_enabled
                self._write_json(self.participants_file, participants)

        logger.info(
            f"Updated media status for user {user_id} in room {room_id}: audio={audio_enabled}, video={video_enabled}")


class ConnectionManager:
    """Enhanced connection manager with user tracking"""

    def __init__(self, storage: FileStorageManager):
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}  # {room_id: {user_id: websocket}}
        self.user_to_room: Dict[WebSocket, tuple] = {}  # {websocket: (room_id, user_id)}
        self.storage = storage

    async def connect(self, websocket: WebSocket, room_id: str, user_id: str, display_name: str):
        """Connect user to room"""
        await websocket.accept()

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


# Initialize storage and connection manager
storage = FileStorageManager()
manager = ConnectionManager(storage)


# API Routes
@app.post("/api/rooms")
async def create_room(request: CreateRoomRequest):
    """Create a new video call room"""
    room_id = storage.create_room(request.max_participants)
    return {
        "room_id": room_id,
        "join_url": f"/room/{room_id}",
        "max_participants": request.max_participants
    }


@app.get("/api/rooms/{room_id}")
async def get_room_info(room_id: str):
    """Get room information and participants"""
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


@app.post("/api/rooms/{room_id}/join")
async def join_room_api(room_id: str, request: JoinRoomRequest):
    """Join a room (called before WebSocket connection)"""
    user_info = storage.join_room(room_id, request.display_name)
    return user_info


@app.patch("/api/rooms/{room_id}/users/{user_id}/media")
async def update_media_status(room_id: str, user_id: str, request: MediaStatusUpdate):
    """Update user's media status (audio/video)"""
    storage.update_media_status(room_id, user_id, request.audio_enabled, request.video_enabled)

    # Notify other users about media change
    message = json.dumps({
        "type": "user-media-changed",
        "user_id": user_id,
        "audio_enabled": request.audio_enabled,
        "video_enabled": request.video_enabled
    })
    await manager.broadcast_to_room(message, room_id, exclude_user=user_id)

    return {"message": "Media status updated"}


@app.delete("/api/rooms/{room_id}")
async def end_room(room_id: str):
    """End a room (disconnect all users)"""
    if room_id in manager.active_connections:
        # Notify all users that room is ending
        end_message = json.dumps({
            "type": "room-ended",
            "message": "Room has been ended by host"
        })
        await manager.broadcast_to_room(end_message, room_id)

        # Disconnect all users
        connections = list(manager.active_connections[room_id].values())
        for connection in connections:
            try:
                await connection.close()
            except:
                pass

        # Clean up
        del manager.active_connections[room_id]

    return {"message": "Room ended successfully"}


@app.get("/")
async def get_join_page():
    """Main landing page - redirect to join page"""
    return FileResponse("static/room.html")  # This should be your join page

@app.get("/join")
async def get_join_page_explicit():
    """Join page"""
    return FileResponse("static/room.html")  # Your join page HTML

@app.get("/room/{room_id}")
async def get_room_interface(room_id: str):
    """Video call interface"""
    return FileResponse("static/index.html")  # Your main video call HTML


# Enhanced WebSocket endpoint
@app.websocket("/ws/{room_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, user_id: str):
    """Enhanced WebSocket endpoint with user_id"""

    # Get user info from storage
    participants = storage.get_room_participants(room_id)
    user_info = next((p for p in participants if p["user_id"] == user_id), None)

    if not user_info:
        await websocket.close(code=4004, reason="User not found in room")
        return

    await manager.connect(websocket, room_id, user_id, user_info["display_name"])

    try:
        while True:
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                message_type = message.get("type", "unknown")

                logger.info(f"Received {message_type} from user {user_id} in room {room_id}")

                # Handle different message types
                if message_type in ["webrtc-offer", "webrtc-answer", "ice-candidate"]:
                    # Route WebRTC signaling messages to specific user
                    target_user = message.get("to_user")
                    if target_user:
                        message["from_user"] = user_id
                        await manager.send_to_user(json.dumps(message), room_id, target_user)
                    else:
                        logger.warning(f"WebRTC message missing to_user field: {message_type}")

                elif message_type == "media-toggle":
                    # Handle media state changes
                    audio_enabled = message.get("audio_enabled", True)
                    video_enabled = message.get("video_enabled", True)

                    # Update storage
                    storage.update_media_status(room_id, user_id, audio_enabled, video_enabled)

                    # Broadcast to other users
                    broadcast_message = json.dumps({
                        "type": "user-media-changed",
                        "user_id": user_id,
                        "audio_enabled": audio_enabled,
                        "video_enabled": video_enabled
                    })
                    await manager.broadcast_to_room(broadcast_message, room_id, exclude_user=user_id)

                else:
                    # Broadcast other messages to all users in room
                    message["from_user"] = user_id
                    await manager.broadcast_to_room(json.dumps(message), room_id, exclude_user=user_id)

            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received from user {user_id}: {data}")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON format"
                }))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id} in room {room_id}")
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Unexpected error in websocket for user {user_id}: {e}")
        await manager.disconnect(websocket)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "active_rooms": len(manager.active_connections),
        "total_connections": sum(len(users) for users in manager.active_connections.values())
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)