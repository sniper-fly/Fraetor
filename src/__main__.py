from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from src.config import SERVER_HOST, SERVER_PORT, init_secrets

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    load_dotenv(_PROJECT_ROOT / ".env")
    init_secrets()
    uvicorn.run("src.app:app", host=SERVER_HOST, port=SERVER_PORT)


if __name__ == "__main__":
    main()
