import time
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, create_engine, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from flux_batch.service.scribe.models import Base, EventModel, EventRecord, JobModel, JobRecord


def _record_event_internal(session, cluster: str, event: Dict[str, Any]):
    """
    Shared synchronous logic for recording events.
    Used by both Sync and Async backends.
    """
    job_id = event.get("id")
    event_type = event.get("type")
    data = event.get("payload", {})
    timestamp = event.get("timestamp", time.time())

    new_event = EventModel(
        job_id=job_id,
        cluster=cluster,
        timestamp=timestamp,
        event_type=event_type,
        payload=data,
    )
    session.add(new_event)

    if event_type == "submit":
        stmt = select(JobModel).where(and_(JobModel.job_id == job_id, JobModel.cluster == cluster))
        job = session.execute(stmt).scalar_one_or_none()

        if not job:
            job = JobModel(
                job_id=job_id,
                cluster=cluster,
                user=str(data.get("userid", "unknown")),
                state="submitted",
                workdir=data.get("cwd", ""),
                submit_time=timestamp,
                last_updated=timestamp,
            )
            session.add(job)
        else:
            job.state = "submitted"
            job.last_updated = timestamp

    # state transitions
    elif event_type == "state" or (event_type and event_type.endswith(".finish")):
        state_name = data.get("state_name", event_type)
        stmt = select(JobModel).where(and_(JobModel.job_id == job_id, JobModel.cluster == cluster))
        job = session.execute(stmt).scalar_one_or_none()
        if job:
            job.state = state_name
            job.last_updated = time.time()
            if "status" in data:
                job.exit_code = data["status"]


class AsyncSQLAlchemyBackend:
    """
    Asynchronous backend for the MCP Gateway.
    """

    def __init__(self, db_url: str):
        self.engine = create_async_engine(db_url, echo=False)
        self.SessionLocal = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self):
        await self.engine.dispose()

    async def record_event(self, cluster: str, event: Dict[str, Any]):
        async with self.SessionLocal() as session:
            # run_sync bridges our shared logic into the async session
            await session.run_sync(_record_event_internal, cluster, event)
            await session.commit()

    async def get_job(self, cluster: str, job_id: int) -> Optional[JobRecord]:
        async with self.SessionLocal() as session:
            result = await session.execute(
                select(JobModel).where(and_(JobModel.job_id == job_id, JobModel.cluster == cluster))
            )
            job = result.scalar_one_or_none()
            return job.to_record() if job else None

    async def get_event_history(self, cluster: str, job_id: int) -> List[EventRecord]:
        async with self.SessionLocal() as session:
            result = await session.execute(
                select(EventModel)
                .where(and_(EventModel.job_id == job_id, EventModel.cluster == cluster))
                .order_by(EventModel.timestamp.asc())
            )
            return [e.to_record() for e in result.scalars().all()]

    async def search_jobs(
        self, cluster: str = None, state: str = None, limit: int = 10
    ) -> List[JobRecord]:
        async with self.SessionLocal() as session:
            stmt = select(JobModel)
            if cluster:
                stmt = stmt.where(JobModel.cluster == cluster)
            if state:
                stmt = stmt.where(JobModel.state == state)
            result = await session.execute(stmt.limit(limit))
            return [j.to_record() for j in result.scalars().all()]


class SQLAlchemyBackend:
    """
    Synchronous backend for the standalone Scribe daemon.
    """

    def __init__(self, db_url: str):
        # strip 'aiosqlite+' or similar if passed from shared config
        url = db_url.replace("+aiosqlite", "").replace("+asyncpg", "")
        self.engine = create_engine(url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def initialize(self):
        Base.metadata.create_all(self.engine)

    def close(self):
        self.engine.dispose()

    def record_event(self, cluster: str, event: Dict[str, Any]):
        with self.SessionLocal() as session:
            with session.begin():
                _record_event_internal(session, cluster, event)

    def get_unwatched_job_ids(self, cluster: str) -> List[int]:
        """Specific for Scribe: find jobs that need a watcher."""
        with self.SessionLocal() as session:
            stmt = select(JobModel.job_id).where(
                and_(JobModel.cluster == cluster, JobModel.state == "submitted")
            )
            return list(session.execute(stmt).scalars().all())

    def mark_job_as_watched(self, cluster: str, job_id: int):
        with self.SessionLocal() as session:
            with session.begin():
                session.execute(
                    update(JobModel)
                    .where(and_(JobModel.job_id == job_id, JobModel.cluster == cluster))
                    .values(state="watching")
                )
