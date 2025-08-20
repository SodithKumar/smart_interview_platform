from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from config import APP_NAME, APP_VERSION, ALLOWED_ORIGINS, logger
from endpoints import rooms_endpoint, health_endpoint, websocket_routes_endpoint, pages_endpoint, janus_endpoint
from endpoints.health_endpoint import health_check

app = FastAPI(title=APP_NAME, version=APP_VERSION)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
app.include_router(rooms_endpoint.router)
app.include_router(websocket_routes_endpoint.router)
app.include_router(health_endpoint.router)
app.include_router(pages_endpoint.router)

if __name__ == "__main__":
    import uvicorn
    from config import HOST, PORT, DEBUG

    logger.info(f"Starting server on {HOST}:{PORT} (debug={DEBUG})")
    uvicorn.run("main:app", host=HOST, port=PORT, reload=DEBUG)
