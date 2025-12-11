from datetime import datetime
from typing import Optional, List
from enum import Enum
from sqlalchemy import BigInteger, String, Integer, Boolean, DateTime, ForeignKey, Enum as SqEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class MatchStatus(str, Enum):
    PENDING = "PENDING"
    FINISHED = "FINISHED"

class PredictionType(str, Enum):
    PRIME = "PRIME"
    REPECHAJE = "REPECHAJE"
    FAIL = "FAIL"
    PENDING = "PENDING"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True) # WhatsApp Phone Number
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    predictions: Mapped[List["Prediction"]] = relationship(back_populates="user")
    score_adjustments: Mapped[List["ScoreAdjustment"]] = relationship(back_populates="user")

class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    home_team: Mapped[str] = mapped_column(String, nullable=False)
    away_team: Mapped[str] = mapped_column(String, nullable=False)
    match_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    goals_home: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    goals_away: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[MatchStatus] = mapped_column(SqEnum(MatchStatus), default=MatchStatus.PENDING)

    predictions: Mapped[List["Prediction"]] = relationship(back_populates="match")

class Prediction(Base):
    __tablename__ = "predictions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    pred_home: Mapped[int] = mapped_column(Integer, nullable=False)
    pred_away: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[PredictionType] = mapped_column(SqEnum(PredictionType), default=PredictionType.PENDING)

    user: Mapped["User"] = relationship(back_populates="predictions")
    match: Mapped["Match"] = relationship(back_populates="predictions")

class ScoreAdjustment(Base):
    __tablename__ = "score_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    points: Mapped[int] = mapped_column(Integer, nullable=False) # Can be negative
    reason: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="score_adjustments")

class GameConfig(Base):
    __tablename__ = "game_config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
