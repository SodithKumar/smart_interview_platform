import os
import logging
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# -------------------
# App Configurations
# -------------------
APP_NAME = "WebRTC Video Call Server"
APP_VERSION = "1.0.0"

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Allowed CORS origins (default: all)
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# Data storage folder
DATA_DIR = os.getenv("DATA_DIR", "data")

# -------------------
# Logging Configuration
# -------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(APP_NAME)
