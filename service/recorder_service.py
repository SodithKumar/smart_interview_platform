# service/recorder_service.py
import os
from datetime import datetime
from typing import Dict, Tuple, Optional, Any

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiortc.contrib.media import MediaRecorder
import logging
logger = logging.getLogger(__name__)

class RecorderSession:
    """
    One session per (room_id, user_id). Holds a single RTCPeerConnection and MediaRecorder.
    Supports renegotiation (e.g., adding/removing screen share later).
    """
    def __init__(self, base_dir: str, room_id: str, user_id: str):
        self.base_dir = base_dir
        self.room_id = room_id
        self.user_id = user_id
        self.pc: Optional[RTCPeerConnection] = None
        self.recorder: Optional[MediaRecorder] = None
        self.recorder_started = False

        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        self.out_dir = os.path.join(self.base_dir, room_id, user_id)
        os.makedirs(self.out_dir, exist_ok=True)
        self.out_file = os.path.join(self.out_dir, f"{ts}.mp4")

    async def _ensure_pc(self):
        if self.pc is not None:
            return
        self.pc = RTCPeerConnection()

        @self.pc.on("track")
        async def on_track(track):
            logger.info(f"[recorder] track {track.kind} {self.room_id}/{self.user_id}")
            if self.recorder is None:
                try:
                    # use mp4 so default codecs (aac + libx264) are valid
                    self.recorder = MediaRecorder(self.out_file, format="mp4")
                except Exception as e:
                    logger.exception("[recorder] failed to create MediaRecorder: %s", e)
                    from aiortc.contrib.media import MediaBlackhole
                    self.recorder = MediaBlackhole()

            try:
                self.recorder.addTrack(track)
            except Exception as e:
                logger.exception("[recorder] failed to add track: %s", e)
                return

            if not self.recorder_started:
                try:
                    await self.recorder.start()
                    self.recorder_started = True
                    logger.info(f"[recorder] started recording to {self.out_file}")
                except Exception as e:
                    logger.exception("[recorder] failed to start recorder: %s", e)

            @track.on("ended")
            async def _ended():
                logger.info(f"[recorder] {track.kind} ended {self.room_id}/{self.user_id}")

    async def start_or_renegotiate(self, offer_sdp: str, offer_type: str) -> Dict[str, Any]:
        await self._ensure_pc()
        # set remote (offer) and answer
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type=offer_type))
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        return {"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type}

    async def add_ice_candidate(self, candidate: Optional[dict]):
        if not self.pc:
            return
        if candidate and candidate.get("candidate"):
            ice = RTCIceCandidate(
                sdpMid=candidate.get("sdpMid"),
                sdpMLineIndex=candidate.get("sdpMLineIndex"),
                candidate=candidate.get("candidate"),
            )
            await self.pc.addIceCandidate(ice)
        else:
            # end-of-candidates
            await self.pc.addIceCandidate(None)

    async def stop(self):
        # Close recorder first so file finalizes and is playable
        try:
            if self.recorder_started and self.recorder:
                await self.recorder.stop()
        except Exception as e:
            logger.warning(f"[recorder] stop recorder error: {e}")
        # Close PC
        try:
            if self.pc:
                await self.pc.close()
        except Exception as e:
            logger.warning(f"[recorder] close pc error: {e}")
        self.pc = None
        self.recorder = None
        self.recorder_started = False

class RecorderManager:
    """
    Holds all RecorderSessions keyed by (room_id, user_id)
    """
    def __init__(self, base_dir: str = "recordings"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.sessions: Dict[Tuple[str, str], RecorderSession] = {}

    def _key(self, room_id: str, user_id: str): return (room_id, user_id)

    async def start_or_renegotiate(self, room_id: str, user_id: str, offer_sdp: str, offer_type: str):
        key = self._key(room_id, user_id)
        if key not in self.sessions:
            self.sessions[key] = RecorderSession(self.base_dir, room_id, user_id)
        return await self.sessions[key].start_or_renegotiate(offer_sdp, offer_type)

    async def add_ice(self, room_id: str, user_id: str, candidate: Optional[dict]):
        key = self._key(room_id, user_id)
        if key in self.sessions:
            await self.sessions[key].add_ice_candidate(candidate)

    async def stop(self, room_id: str, user_id: str):
        key = self._key(room_id, user_id)
        if key in self.sessions:
            await self.sessions[key].stop()
            del self.sessions[key]

    async def stop_all_in_room(self, room_id: str):
        to_stop = [k for k in list(self.sessions.keys()) if k[0] == room_id]
        for _, uid in to_stop:
            await self.stop(room_id, uid)
