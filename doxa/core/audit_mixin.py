from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class AuditMixin(BaseModel):
    # todo: isn't this more a db thing?
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp.",
    )
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp.")
