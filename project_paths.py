from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
PROMPTS_DIR = PROJECT_DIR / "prompts"
OUTPUT_DIR = PROJECT_DIR / "out"
ENV_FILE = PROJECT_DIR / ".env"