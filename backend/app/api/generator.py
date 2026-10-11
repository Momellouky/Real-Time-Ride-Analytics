from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.generator.service import GeneratorConflictError, GeneratorService
from app.models.generator import GeneratorStartInput, GeneratorStatus
from app.services.kafka_producer import KafkaPublishError

router = APIRouter(prefix='/api/v2/generator', tags=['generator'])


def get_generator(request: Request) -> GeneratorService:
    return request.app.state.generator


Generator = Annotated[GeneratorService, Depends(get_generator)]


@router.post('/start', status_code=202, response_model=GeneratorStatus)
async def start_generator(payload: GeneratorStartInput, generator: Generator):
    try:
        return await generator.start(**payload.model_dump())
    except GeneratorConflictError as exc:
        raise HTTPException(409, 'Generator is already active. Stop it before starting a fresh run.') from exc
    except KafkaPublishError as exc:
        raise HTTPException(503, 'Unable to start the generator. Check its status before retrying.') from exc


@router.post('/stop', response_model=GeneratorStatus)
async def stop_generator(generator: Generator):
    # ERROR remains visible in the typed response if draining could not complete.
    return await generator.stop()


@router.get('/status', response_model=GeneratorStatus)
async def generator_status(generator: Generator):
    return generator.status()
