from sqlalchemy import String
from sqlalchemy.orm import Mapped,mapped_column
from app.db.base import Base,TimestampMixin

class AgentControllerSetting(TimestampMixin,Base):
    __tablename__='agent_controller_settings'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    controller:Mapped[str]=mapped_column(String(20),nullable=False)
    updated_by:Mapped[str|None]=mapped_column(String(36))
