from pydantic import BaseModel


class CreateRoomRequest(BaseModel):
    max_participants: int = 100


class JoinRoomRequest(BaseModel):
    display_name: str


class MediaStatusUpdate(BaseModel):
    audio_enabled: bool
    video_enabled: bool
