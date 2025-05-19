from fastapi import APIRouter, HTTPException, Depends, status
from models import Driver, DriverCreate
from database import drivers_collection
from bson import ObjectId
from auth import get_current_user, get_current_user_expired_ok

router = APIRouter()

def driver_helper(driver) -> dict:
    return {
        "id": str(driver["_id"]),
        "name": driver["name"],
        "password": driver["password"]
    }

@router.post("/", response_model=Driver)
async def create_driver(driver: DriverCreate, current_user = Depends(get_current_user_expired_ok)):
    # Verificar se motorista com mesmo nome já existe
    existing_driver = await drivers_collection.find_one({"name": driver.name})
    if existing_driver:
        raise HTTPException(
            status_code=400, 
            detail="Motorista com este nome já existe"
        )
    
    try:
        # Para versões mais recentes do Pydantic
        driver_dict = driver.model_dump()
    except AttributeError:
        # Para versões mais antigas do Pydantic
        driver_dict = driver.dict()
    
    new_driver = await drivers_collection.insert_one(driver_dict)
    created_driver = await drivers_collection.find_one({"_id": new_driver.inserted_id})
    return driver_helper(created_driver)

@router.post("", response_model=Driver)
async def create_driver_no_slash(driver: DriverCreate, current_user = Depends(get_current_user_expired_ok)):
    """Endpoint alternativo para criar motorista sem barra no final"""
    return await create_driver(driver, current_user)

@router.get("/")
async def get_drivers(current_user = Depends(get_current_user_expired_ok)):
    drivers = []
    async for driver in drivers_collection.find({}):
        drivers.append(driver_helper(driver))
    return drivers

@router.get("", response_model=list[Driver])
async def get_drivers_no_slash(current_user = Depends(get_current_user_expired_ok)):
    """Endpoint alternativo para listar motoristas sem barra no final"""
    return await get_drivers(current_user)

@router.get("/{driver_id}", response_model=Driver)
async def get_driver(driver_id: str, current_user = Depends(get_current_user_expired_ok)):
    driver = await drivers_collection.find_one({"_id": ObjectId(driver_id)})
    if driver:
        return driver_helper(driver)
    raise HTTPException(status_code=404, detail="Motorista não encontrado")

@router.put("/{driver_id}")
async def update_driver(driver_id: str, driver_data: DriverCreate, current_user = Depends(get_current_user)):
    try:
        # Para versões mais recentes do Pydantic
        driver_dict = driver_data.model_dump()
    except AttributeError:
        # Para versões mais antigas do Pydantic
        driver_dict = driver_data.dict()
    
    # Verificar se o motorista existe
    if not await drivers_collection.find_one({"_id": ObjectId(driver_id)}):
        raise HTTPException(status_code=404, detail="Motorista não encontrado")
    
    # Atualizar dados do motorista
    updated_driver = await drivers_collection.update_one(
        {"_id": ObjectId(driver_id)},
        {"$set": driver_dict}
    )
    
    if updated_driver.modified_count == 1:
        updated_doc = await drivers_collection.find_one({"_id": ObjectId(driver_id)})
        return driver_helper(updated_doc)
    raise HTTPException(status_code=404, detail="Motorista não encontrado ou nenhuma alteração feita")

@router.delete("/{driver_id}")
async def delete_driver(driver_id: str, current_user = Depends(get_current_user)):
    # Verificar se o motorista existe
    if not await drivers_collection.find_one({"_id": ObjectId(driver_id)}):
        raise HTTPException(status_code=404, detail="Motorista não encontrado")
    
    # Excluir o motorista
    delete_result = await drivers_collection.delete_one({"_id": ObjectId(driver_id)})
    
    if delete_result.deleted_count == 1:
        return {"message": "Motorista excluído com sucesso"}
    raise HTTPException(status_code=500, detail="Erro ao excluir motorista")
