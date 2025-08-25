from fastapi import APIRouter

from repos.file_storage_manager_repo import FileStorageManager
from service.connection_manager_service import ConnectionManager

router = APIRouter(tags=["Health"])

storage = FileStorageManager()
manager = ConnectionManager(storage)


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "active_rooms": len(manager.active_connections),
        "total_connections": sum(len(users) for users in manager.active_connections.values())
    }
