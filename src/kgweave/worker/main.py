# @summary
# Worker entry point: connects to Temporal, registers activities on
# KG_TASK_QUEUE, runs until cancelled. The concrete KGService must be
# bound via kgweave.worker.set_service() before run_worker().
# Exports: run_worker
# Deps: temporalio.client, temporalio.worker, kgweave.contracts,
#       kgweave.worker.activities
# @end-summary
"""KGWeave Temporal worker entry point."""

from __future__ import annotations

import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from kgweave.contracts import KG_TASK_QUEUE
from kgweave.service import build_default_service
from kgweave.worker.activities import (
    kg_delete_by_source_activity,
    kg_health_activity,
    kg_phase2b_activity,
    set_service,
)

logger = logging.getLogger("kgweave.worker.main")

DEFAULT_TARGET_HOST = "localhost:7233"
DEFAULT_MAX_CONCURRENT = 4


async def run_worker(
    *,
    target_host: str | None = None,
    task_queue: str | None = None,
    max_concurrent_activities: int | None = None,
) -> None:
    """Connect to Temporal and run the KGWeave worker until cancelled.

    Args:
        target_host: Temporal frontend, defaults to env ``TEMPORAL_TARGET_HOST``.
        task_queue: Override for ``KG_TASK_QUEUE`` (mainly for tests).
        max_concurrent_activities: Slot pool, defaults to env ``KG_WORKER_SLOTS``.
    """
    target = target_host or os.environ.get("TEMPORAL_TARGET_HOST", DEFAULT_TARGET_HOST)
    queue = task_queue or KG_TASK_QUEUE
    slots = max_concurrent_activities or int(
        os.environ.get("KG_WORKER_SLOTS", DEFAULT_MAX_CONCURRENT)
    )

    use_gliner = os.environ.get("KG_USE_GLINER", "0") in ("1", "true", "True")
    set_service(build_default_service(use_gliner=use_gliner))

    client = await Client.connect(target)
    worker = Worker(
        client,
        task_queue=queue,
        max_concurrent_activities=slots,
        activities=[
            kg_phase2b_activity,
            kg_delete_by_source_activity,
            kg_health_activity,
        ],
    )
    logger.info(
        "kgweave worker started target=%s queue=%s slots=%d",
        target, queue, slots,
    )
    await worker.run()


def main() -> None:
    """Entry point for `python -m kgweave.worker.main`."""
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
