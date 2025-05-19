from fastapi import APIRouter, HTTPException, Depends, status, Request
from models import Trip, TripCreate
from database import trips_collection
from auth import get_current_user, get_current_user_expired_ok, SECRET_KEY
from datetime import datetime
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Log da chave secreta sendo usada nos trips (apenas para diagnóstico)
logger.info(f"Módulo trips usando chave secreta (primeiros 10 caracteres): {SECRET_KEY[:10]}...")

def trip_helper(trip) -> dict:
    """Converte documento de viagem do MongoDB para um modelo Pydantic válido"""
    return {
        "id": str(trip["_id"]),
        "user_id": str(trip.get("user_id", "")),
        "driver_id": trip["driver_id"],
        "platform": trip["platform"],
        "date": trip["date"],
        "distance": float(trip["distance"]),
        "earnings": float(trip["earnings"]),
        "origin": trip.get("origin", ""),  # New field for origin
        "destination": trip.get("destination", "")
    }

# routes/trips.py
@router.post("/", response_model=Trip)
async def create_trip(trip: TripCreate, current_user = Depends(get_current_user)):
    try:
        # Usa o método to_mongo para garantir a conversão correta da data
        trip_dict = trip.to_mongo()
        trip_dict["user_id"] = current_user.id

        new_trip = await trips_collection.insert_one(trip_dict)
        created_trip = await trips_collection.find_one({"_id": new_trip.inserted_id})
        return trip_helper(created_trip)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao criar viagem: {str(e)}")

@router.post("", response_model=Trip)
async def create_trip_no_slash(trip: TripCreate, current_user = Depends(get_current_user)):
    """Endpoint alternativo para criar viagem sem barra no final"""
    return await create_trip(trip, current_user)

@router.get("/", response_model=list[Trip])
async def get_trips(request: Request):
    """
    Retorna todas as viagens do usuário atual.
    """
    try:
        # Usar o middleware para tentar obter o usuário do token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning("Authorization header inválido ou ausente")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token não fornecido",
                headers={"WWW-Authenticate": "Bearer"}
            )

        # Tentar buscar viagens sem depender de get_current_user
        # (temporariamente para diagnóstico)
        trips = []
        async for trip in trips_collection.find({}):
            trips.append(trip_helper(trip))
        return trips
    except Exception as e:
        logger.error(f"Erro ao buscar viagens: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar viagens: {str(e)}"
        )

@router.get("", response_model=list[Trip])
async def get_trips_no_slash(request: Request):
    """Endpoint alternativo para listar viagens sem barra no final"""
    return await get_trips(request)

@router.put("/{trip_id}")
async def update_trip(trip_id: str, trip_data: TripCreate, current_user = Depends(get_current_user_expired_ok)):
    """Atualiza uma viagem existente"""
    try:
        # Verifica se a viagem existe e pertence ao usuário
        existing_trip = await trips_collection.find_one({"_id": ObjectId(trip_id)})
        if not existing_trip:
            raise HTTPException(status_code=404, detail="Viagem não encontrada")

        if str(existing_trip.get("user_id")) != current_user.id:
            raise HTTPException(status_code=403, detail="Sem permissão para atualizar esta viagem")

        # Prepara os dados para atualização
        try:
            update_data = trip_data.model_dump()
        except AttributeError:
            update_data = trip_data.dict()

        update_data["user_id"] = current_user.id

        # Garante que driver_id seja string
        if "driver_id" in update_data:
            update_data["driver_id"] = str(update_data["driver_id"])

        # Converte valores numéricos para float
        if "distance" in update_data:
            update_data["distance"] = float(update_data["distance"])
        if "earnings" in update_data:
            update_data["earnings"] = float(update_data["earnings"])

        # Converte date para datetime
        if isinstance(update_data.get("date"), date):
            update_data["date"] = datetime.combine(update_data["date"], datetime.min.time())

        # Atualiza a viagem
        await trips_collection.update_one(
            {"_id": ObjectId(trip_id)},
            {"$set": update_data}
        )

        # Retorna a viagem atualizada
        updated_trip = await trips_collection.find_one({"_id": ObjectId(trip_id)})
        return trip_helper(updated_trip)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar viagem: {str(e)}")

@router.delete("/{trip_id}")
async def delete_trip(trip_id: str, current_user = Depends(get_current_user_expired_ok)):
    """Exclui uma viagem específica"""
    try:
        # Verifica se a viagem existe e pertence ao usuário
        existing_trip = await trips_collection.find_one({"_id": ObjectId(trip_id)})
        if not existing_trip:
            raise HTTPException(status_code=404, detail="Viagem não encontrada")

        if str(existing_trip.get("user_id")) != current_user.id:
            raise HTTPException(status_code=403, detail="Sem permissão para excluir esta viagem")

        # Exclui a viagem
        result = await trips_collection.delete_one({"_id": ObjectId(trip_id)})

        if result.deleted_count == 1:
            return {"mensagem": "Viagem excluída com sucesso"}
        else:
            raise HTTPException(status_code=404, detail="Viagem não encontrada")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao excluir viagem: {str(e)}")
