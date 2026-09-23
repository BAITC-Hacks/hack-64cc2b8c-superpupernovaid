from functools import lru_cache

from app.intelligence.integration import AnalysisCoordinator
from app.intelligence.pipeline.dependencies import get_intelligence_service, shutdown_intelligence


@lru_cache
def get_analysis_coordinator():
    pipeline = get_intelligence_service()
    return AnalysisCoordinator(pipeline) if pipeline is not None else None


async def shutdown_analysis():
    if get_analysis_coordinator.cache_info().currsize:
        coordinator = get_analysis_coordinator()
        if coordinator is not None:
            await coordinator.close()
    await shutdown_intelligence()
    get_analysis_coordinator.cache_clear()


async def analyze_meeting(meeting_id):
    """Application entry point for HTTP-independent pipeline/worker callers."""
    from app.intelligence.pipeline.errors import AgentConfigurationError

    coordinator = get_analysis_coordinator()
    if coordinator is None:
        raise AgentConfigurationError
    return await coordinator.analyze(meeting_id)
