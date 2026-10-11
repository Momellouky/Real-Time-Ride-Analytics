from pydantic import BaseModel, ConfigDict, Field

from app.generator.service import GeneratorState


class GeneratorStartInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_count: int = Field(gt=0, strict=True)
    driver_count: int = Field(gt=0, strict=True)
    target_events_per_second: int = Field(gt=0, strict=True)


class GeneratorDiagnostics(BaseModel):
    idle_users: int = Field(default=0, ge=0)
    waiting_users: int = Field(default=0, ge=0)
    users_in_ride: int = Field(default=0, ge=0)
    offline_drivers: int = Field(default=0, ge=0)
    waiting_drivers: int = Field(default=0, ge=0)
    assigned_drivers: int = Field(default=0, ge=0)


class GeneratorStatus(BaseModel):
    simulation_id: str | None
    status: GeneratorState
    target_events_per_second: int = Field(ge=0)
    actual_events_per_second: float = Field(ge=0)
    generated_events: int = Field(ge=0)
    published_events: int = Field(ge=0)
    user_pool_size: int = Field(ge=0)
    driver_pool_size: int = Field(ge=0)
    in_memory: GeneratorDiagnostics
    last_error: str | None
