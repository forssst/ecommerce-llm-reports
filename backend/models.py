from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from database import Base


def _now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    databases = relationship("Database", back_populates="owner")
    queries = relationship("Query", back_populates="user")


class Database(Base):
    __tablename__ = "databases"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    schema_json = Column(JSON)
    uploaded_at = Column(DateTime, default=_now)
    owner = relationship("User", back_populates="databases")
    queries = relationship("Query", back_populates="database")


class Query(Base):
    __tablename__ = "queries"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    database_id = Column(Integer, ForeignKey("databases.id"), nullable=False)
    prompt_nl = Column(Text, nullable=False)
    generated_sql = Column(Text)
    status = Column(String, default="pending")
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)
    user = relationship("User", back_populates="queries")
    database = relationship("Database", back_populates="queries")
    report = relationship("Report", back_populates="query", uselist=False)


class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    query_id = Column(Integer, ForeignKey("queries.id"), nullable=False)
    metabase_question_id = Column(Integer)
    metabase_dashboard_id = Column(Integer)
    public_link = Column(String)
    created_at = Column(DateTime, default=_now)
    query = relationship("Query", back_populates="report")
