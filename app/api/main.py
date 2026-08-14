from fastapi import APIRouter

from app.api.routes import (
    config,
    draft_series,
    fantasy,
    import_export,
    koth,
    login,
    maps,
    matches,
    public,
    scores,
    seasons,
    series,
    stats,
    teams,
    users,
)

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(teams.router)
api_router.include_router(matches.router)
api_router.include_router(seasons.router)
api_router.include_router(import_export.router)
api_router.include_router(public.router)
api_router.include_router(series.router)
api_router.include_router(draft_series.router)
api_router.include_router(maps.router)
api_router.include_router(scores.router)
api_router.include_router(fantasy.router)
api_router.include_router(config.router)
api_router.include_router(koth.router)
api_router.include_router(stats.router)
