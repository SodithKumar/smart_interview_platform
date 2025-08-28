import os
from threading import Lock
import json
import uuid
from datetime import datetime
from fastapi import HTTPException
import logging
from typing import List, Optional

# Configure logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

    def create_room(self, max_participants: int = 100) -> str:
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

            # room = rooms[room_id]
            # if room["current_participants"] >= room["max_participants"]:
            #     raise HTTPException(status_code=400, detail="Room is full")

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
