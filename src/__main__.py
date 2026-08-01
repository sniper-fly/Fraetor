from pathlib import Path

import uvicorn
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    load_dotenv(_PROJECT_ROOT / ".env")
    from src.containers import Container  # noqa: PLC0415

    settings = Container().settings()
    uvicorn.run(
        "src.presentation.app:app", host=settings.server_host, port=settings.server_port
    )


if __name__ == "__main__":
    main()
