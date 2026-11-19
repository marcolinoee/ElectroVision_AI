"""CLI runner to execute all idempotent database seeds."""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.database import get_async_session_factory
from app.core.logging import configure_logging, get_logger
from app.seeds.rule_metadata_seed import seed_rule_metadata
from app.seeds.sinapi_eletrica_seed import seed_sinapi_items


async def run_all_seeds() -> dict[str, int]:
    settings = get_settings()
    configure_logging(settings.electrovision_log_level)
    logger = get_logger(__name__)

    session_factory = get_async_session_factory()
    async with session_factory() as session:
        rules_inserted = await seed_rule_metadata(session)
        sinapi_inserted = await seed_sinapi_items(session)
        await session.commit()

    summary = {"rules_inserted": rules_inserted, "sinapi_inserted": sinapi_inserted}
    logger.info("seeds_completed", **summary)
    return summary


if __name__ == "__main__":
    asyncio.run(run_all_seeds())
