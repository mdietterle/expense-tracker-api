# routes/trips.py
from datetime import datetime
from fastapi import APIRouter, HTTPException
from models import Trip, TripCreate
from database import trips_collection
from auth import get_current_user
from fastapi import Depends

router = APIRouter()

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
        "origin": trip.get("origin", ""),  # Adicionado campo origin
        "destination": trip.get("destination", "")  # Adicionado campo destination
    }

@router.post("/", response_model=Trip)
async def create_trip(trip: TripCreate, current_user = Depends(get_current_user)):
    try:
        trip_dict = trip.model_dump()  # Usar model_dump() ao invés de dict()
        trip_dict["date"] = datetime.combine(trip_dict["date"], datetime.min.time())
        trip_dict["user_id"] = current_user.id

        new_trip = await trips_collection.insert_one(trip_dict)
        created_trip = await trips_collection.find_one({"_id": new_trip.inserted_id})
        return trip_helper(created_trip)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao criar viagem: {str(e)}")