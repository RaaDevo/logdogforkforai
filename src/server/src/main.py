import uvicorn
from fastapi import Depends, FastAPI

from lib.database import create_tables
from parsers.orchestrator import register_pipelines
from routes.auth import get_current_user, router as auth_router
from routes.logs import router as logs_router
from routes.stats import router as stats_router

app = FastAPI()

app.include_router(auth_router)
app.include_router(logs_router)
app.include_router(stats_router)


@app.on_event("startup")
def startup() -> None:
    create_tables()
    register_pipelines()


@app.get("/")
async def root(_: object = Depends(get_current_user)):
    return "Logdog"


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3001)
