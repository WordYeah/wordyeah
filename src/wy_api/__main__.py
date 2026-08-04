from __future__ import annotations

import os

import uvicorn

from .app import ApiSettings, create_app


def main() -> None:
    settings = ApiSettings.from_env()
    uvicorn.run(
        create_app(settings),
        host=settings.bind,
        port=int(os.getenv("WORDYEAH_PORT", "18765")),
    )


if __name__ == "__main__":
    main()
