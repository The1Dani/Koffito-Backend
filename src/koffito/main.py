from fastapi import FastAPI

from .api.routes import items, root

app = FastAPI()
app.include_router(root.router)
app.include_router(items.router)
