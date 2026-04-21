"""Entrypoint for the APEX Serving Layer.

Run with: ``uvicorn services.data_ingestion.serving.main:app --port 8001``
"""

from __future__ import annotations

from services.data_ingestion.serving.app import app

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "services.data_ingestion.serving.main:app",
        host="0.0.0.0",  # noqa: S104
        port=8001,
        log_level="info",
    )
