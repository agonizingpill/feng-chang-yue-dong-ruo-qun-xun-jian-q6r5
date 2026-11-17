from datetime import datetime
from sqlalchemy import String,Float,DateTime,ForeignKey,CheckConstraint,func
from sqlalchemy.orm import Mapped,mapped_column
from .database import Base
class FeedBatch(Base):
    __tablename__='feed_batches'
    id:Mapped[int]=mapped_column(primary_key=True)
    token:Mapped[str]=mapped_column(String(64),unique=True)
    fingerprint:Mapped[str]=mapped_column(String(64))
    state:Mapped[str]=mapped_column(String(24),default='confirmed')
    total_kg:Mapped[float]=mapped_column(Float)
    created_by:Mapped[str]=mapped_column(String(120))
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
class FeedBatchItem(Base):
    __tablename__='feed_batch_items'
    __table_args__=(CheckConstraint('feed_kg>0 AND feed_kg<=3'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_id:Mapped[int]=mapped_column(ForeignKey('feed_batches.id'))
    hive_id:Mapped[int]=mapped_column(ForeignKey('hives.id'))
    visit_id:Mapped[int]=mapped_column(ForeignKey('visits.id'))
    care_id:Mapped[int]=mapped_column(ForeignKey('care_actions.id'),unique=True)
    feed_kg:Mapped[float]=mapped_column(Float)
    anomaly_score:Mapped[float]=mapped_column(Float)
    state:Mapped[str]=mapped_column(String(24),default='issued')
class FeedBatchIssue(Base):
    __tablename__='feed_batch_issues'
    __table_args__=(CheckConstraint('kg>0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    item_id:Mapped[int]=mapped_column(ForeignKey('feed_batch_items.id'))
    lot_id:Mapped[int]=mapped_column(ForeignKey('feed_lots.id'))
    kg:Mapped[float]=mapped_column(Float)
    state:Mapped[str]=mapped_column(String(24),default='issued')
    returned_by:Mapped[str]=mapped_column(String(120),default='')
