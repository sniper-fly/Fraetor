import uvicorn

from src.config import SERVER_HOST, SERVER_PORT, init_secrets


def main() -> None:
    init_secrets()
    uvicorn.run("src.app:app", host=SERVER_HOST, port=SERVER_PORT)


if __name__ == "__main__":
    main()
