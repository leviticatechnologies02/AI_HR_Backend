
from __future__ import annotations
import re
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, field_validator


class CompanyLocationBase(BaseModel):
    name:                   str
    address:                Optional[str]   = None
    city:                   Optional[str]   = None
    state:                  Optional[str]   = None
    country:                Optional[str]   = None
    postal_code:            Optional[str]   = None
    latitude:               Optional[str]   = None
    longitude:              Optional[str]   = None

    timezone:               str
    working_hours_start:    Optional[str]   = None  
    working_hours_end:      Optional[str]   = None  
    weekend_days:           Optional[str]   = None  
    is_default:             bool            = False
    is_active:              bool            = True

    @field_validator("timezone", check_fields=False)
    @classmethod
    def validate_timezone(cls, v):
        # Must look like an IANA name (Asia/Kolkata, America/New_York, UTC) - not free text like "delhi".
        # Format check only, so it does not depend on a timezone database being installed (Windows).
        if v is None:
            return v
        v = v.strip()
        if not re.fullmatch(r"UTC|GMT|[A-Za-z_]+(/[A-Za-z0-9_+\-]+)+", v):
            raise ValueError("Timezone must be a region name such as Asia/Kolkata or America/New_York")
        return v

    @field_validator("name", check_fields=False)
    @classmethod
    def validate_name(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Branch name is required")
        return v

    @field_validator("working_hours_start", "working_hours_end")
    @classmethod
    def validate_time_format(cls, v):
        if v:
            parts = v.split(":")
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                raise ValueError("Time must be in HH:MM format")
        return v


class CompanyLocationCreate(CompanyLocationBase):
    name:     str
    timezone: str


class CompanyLocationUpdate(CompanyLocationBase):
    name:     Optional[str] = None
    timezone: Optional[str] = None


class CompanyLocationResponse(CompanyLocationBase):
    id:             int
    tenant_id:      int
    created_at:     datetime
    updated_at:     datetime
    employee_count: int = 0

    model_config = {"from_attributes": True}


class CompanyLocationListResponse(BaseModel):
    locations: List[CompanyLocationResponse]
    total:     int
