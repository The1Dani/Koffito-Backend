from fastapi import FastAPI

from .api.routes import root, venues

app = FastAPI()
app.include_router(root.router)
app.include_router(venues.router)
