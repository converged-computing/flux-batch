from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy import JSON, Float, Integer, String
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# DTOs are "Public Data Transfer Objects" and they are used by
# our interfaces and tools


@dataclass
class JobRecord:
    """
    Represents a snapshot of a job state.
    Returned by get_job() and search_jobs().
    """

    job_id: int
    cluster: str
    state: str
    user: str
    workdir: Optional[str] = None
    exit_code: Optional[int] = None
    submit_time: float = 0.0
    last_updated: float = 0.0


@dataclass
class EventRecord:
    """
    Represents a single historical event.
    Returned by get_event_history().
    """

    timestamp: float
    event_type: str
    payload: Dict[str, Any]


# Database models for SQLAlchemy ORM


class Base(AsyncAttrs, DeclarativeBase):
    pass


class JobModel(Base):
    __tablename__ = "jobs"

    # Composite Primary Key
    job_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster: Mapped[str] = mapped_column(String(255), primary_key=True)

    state: Mapped[str] = mapped_column(String(50))
    user: Mapped[str] = mapped_column(String(255), nullable=True)
    workdir: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    submit_time: Mapped[float] = mapped_column(Float, default=0.0)
    last_updated: Mapped[float] = mapped_column(Float, default=0.0)

    def to_record(self) -> JobRecord:
        """
        Helper to convert ORM model to public DTO
        """
        return JobRecord(
            job_id=self.job_id,
            cluster=self.cluster,
            state=self.state,
            user=self.user,
            workdir=self.workdir,
            exit_code=self.exit_code,
            submit_time=self.submit_time,
            last_updated=self.last_updated,
        )


class EventModel(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, index=True)
    cluster: Mapped[str] = mapped_column(String(255), index=True)
    timestamp: Mapped[float] = mapped_column(Float)
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON)

    def to_record(self) -> EventRecord:
        """
        Helper to convert ORM model to public DTO
        """
        return EventRecord(
            timestamp=self.timestamp, event_type=self.event_type, payload=self.payload
        )
