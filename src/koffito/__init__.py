import uvicorn


def main() -> None:
    """`uv run koffito` — development server with autoreload."""
    uvicorn.run("koffito.asgi:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
