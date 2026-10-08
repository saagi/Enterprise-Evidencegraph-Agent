from app.config import get_settings
from app.models.openai_gateway import OpenAIGateway


def main() -> None:
    settings = get_settings()
    gateway = OpenAIGateway(settings)

    print("Gateway initialized successfully")


if __name__ == "__main__":
    main()