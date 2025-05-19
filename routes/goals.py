from fastapi import APIRouter, HTTPException
from fastapi import Depends
from models import Goal, GoalCreate
from database import goals_collection, expenses_collection, trips_collection
from bson import ObjectId
from datetime import date, datetime
from auth import get_current_user, get_current_user_expired_ok

router = APIRouter()


def goal_helper(goal) -> dict:
    return {
        "id": str(goal["_id"]),
        "user_id": goal.get("user_id", ""),  # Valor padrão vazio se não existir
        "driver_id": goal["driver_id"],
        "name": goal["name"],
        "target_amount": goal["target_amount"],
        "current_amount": goal.get("current_amount", 0.0),
        "deadline": goal["deadline"]
    }


@router.post("/", response_model=Goal)
async def create_goal(goal: GoalCreate, current_user = Depends(get_current_user_expired_ok)):
    try:
        # Para versões mais recentes do Pydantic, use model_dump em vez de dict()
        try:
            goal_dict = goal.model_dump()
        except AttributeError:
            # Fallback para versões mais antigas do Pydantic
            goal_dict = goal.dict()
            
        goal_dict["user_id"] = current_user.id
        
        # Registrar driver_id original para depuração
        original_driver_id = goal_dict.get("driver_id")
        print(f"Criando meta com driver_id original: {original_driver_id} (tipo: {type(original_driver_id)})")
        
        # Garantir que driver_id seja do tipo string (não ObjectId ou outro tipo)
        if "driver_id" in goal_dict and goal_dict["driver_id"] is not None:
            goal_dict["driver_id"] = str(goal_dict["driver_id"])
            print(f"Driver ID padronizado para string: {goal_dict['driver_id']}")
        
        # Garantir que os valores numéricos sejam tipo float
        if "target_amount" in goal_dict:
            try:
                goal_dict["target_amount"] = float(goal_dict["target_amount"])
            except (ValueError, TypeError):
                print(f"ERRO: Não foi possível converter target_amount para float")
                
        if "current_amount" in goal_dict:
            try:
                goal_dict["current_amount"] = float(goal_dict["current_amount"])
            except (ValueError, TypeError):
                print(f"ERRO: Não foi possível converter current_amount para float")
        
        # Converter date para datetime antes de salvar no MongoDB
        if isinstance(goal_dict.get("deadline"), date):
            goal_dict["deadline"] = datetime.combine(goal_dict["deadline"], datetime.min.time())
        
        new_goal = await goals_collection.insert_one(goal_dict)
        created_goal = await goals_collection.find_one({"_id": new_goal.inserted_id})
        return goal_helper(created_goal)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao criar meta: {str(e)}")

@router.post("", response_model=Goal)
async def create_goal_no_slash(goal: GoalCreate, current_user = Depends(get_current_user_expired_ok)):
    """Endpoint alternativo para criar meta sem barra no final"""
    return await create_goal(goal, current_user)


@router.get("/")
async def get_goals():
    try:
        goals = []
        async for goal in goals_collection.find({}):
            try:
                goals.append(goal_helper(goal))
            except KeyError as e:
                # Log do erro e continua sem adicionar o documento problemático
                print(f"Erro ao processar meta {goal.get('_id')}: {str(e)}")
                continue
        return goals
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar metas: {str(e)}")

@router.get("")
async def get_goals_no_slash():
    """Endpoint alternativo para buscar metas sem barra no final"""
    return await get_goals()


@router.get("/driver/{driver_id}")
async def get_goals_by_driver(driver_id: str):
    goals = []
    async for goal in goals_collection.find({"driver_id": driver_id}):
        goals.append(goal_helper(goal))
    return goals


@router.get("/{goal_id}", response_model=Goal)
async def get_goal(goal_id: str):
    goal = await goals_collection.find_one({"_id": ObjectId(goal_id)})
    if goal:
        return goal_helper(goal)
    raise HTTPException(status_code=404, detail="Meta não encontrada")


@router.put("/{goal_id}/update-progress")
async def update_goal_progress(goal_id: str):
    goal = await goals_collection.find_one({"_id": ObjectId(goal_id)})
    if not goal:
        raise HTTPException(status_code=404, detail="Meta não encontrada")

    driver_id = goal["driver_id"]
    print(f"Atualizando progresso para motorista: {driver_id}")
    
    # Buscar todas as possíveis variações deste driver_id
    all_trips = await trips_collection.find({}).to_list(length=None)
    similar_driver_ids = set()
    for trip in all_trips:
        trip_driver_id = trip.get('driver_id')
        if trip_driver_id and (trip_driver_id.lower() == driver_id.lower() or 
                               trip_driver_id.strip() == driver_id.strip()):
            similar_driver_ids.add(trip_driver_id)
    
    # Adicionar o driver_id original
    similar_driver_ids.add(driver_id)
    print(f"Variações de driver_id encontradas: {similar_driver_ids}")
    
    # Calcular ganhos totais do motorista considerando todas variações
    total_trips = await trips_collection.aggregate([
        {"$match": {"driver_id": {"$in": list(similar_driver_ids)}}},
        {"$group": {"_id": None, "total": {"$sum": {"$toDouble": "$earnings"}}}}
    ]).to_list(length=None)

    total_earnings = total_trips[0]["total"] if total_trips else 0
    print(f"Total de ganhos: {total_earnings}")

    # Calcular despesas totais do motorista considerando todas variações
    total_expenses = await expenses_collection.aggregate([
        {"$match": {"driver_id": {"$in": list(similar_driver_ids)}}},
        {"$group": {"_id": None, "total": {"$sum": {"$toDouble": "$amount"}}}}
    ]).to_list(length=None)

    total_spent = total_expenses[0]["total"] if total_expenses else 0
    print(f"Total de despesas: {total_spent}")

    # Calcular lucro líquido
    net_profit = total_earnings - total_spent

    # Atualizar meta
    await goals_collection.update_one(
        {"_id": ObjectId(goal_id)},
        {"$set": {"current_amount": net_profit}}
    )

    updated_goal = await goals_collection.find_one({"_id": ObjectId(goal_id)})
    return goal_helper(updated_goal)


@router.put("/{goal_id}")
async def update_goal(goal_id: str, goal_data: GoalCreate, current_user = Depends(get_current_user_expired_ok)):
    """Atualiza uma meta existente"""
    try:
        # Verifica se a meta existe e pertence ao usuário
        existing_goal = await goals_collection.find_one({"_id": ObjectId(goal_id)})
        if not existing_goal:
            raise HTTPException(status_code=404, detail="Meta não encontrada")

        if str(existing_goal.get("user_id")) != current_user.id:
            raise HTTPException(status_code=403, detail="Sem permissão para atualizar esta meta")

        # Prepara os dados para atualização
        try:
            update_data = goal_data.model_dump()
        except AttributeError:
            update_data = goal_data.dict()

        update_data["user_id"] = current_user.id

        # Garante que driver_id seja string
        if "driver_id" in update_data:
            update_data["driver_id"] = str(update_data["driver_id"])

        # Converte valores numéricos para float
        if "target_amount" in update_data:
            update_data["target_amount"] = float(update_data["target_amount"])

        # Converte date para datetime
        if isinstance(update_data.get("deadline"), date):
            update_data["deadline"] = datetime.combine(update_data["deadline"], datetime.min.time())

        # Atualiza a meta
        await goals_collection.update_one(
            {"_id": ObjectId(goal_id)},
            {"$set": update_data}
        )

        # Retorna a meta atualizada
        updated_goal = await goals_collection.find_one({"_id": ObjectId(goal_id)})
        return goal_helper(updated_goal)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar meta: {str(e)}")

@router.delete("/{goal_id}")
async def delete_goal(goal_id: str, current_user = Depends(get_current_user_expired_ok)):
    """Exclui uma meta específica"""
    try:
        # Verifica se a meta existe e pertence ao usuário
        existing_goal = await goals_collection.find_one({"_id": ObjectId(goal_id)})
        if not existing_goal:
            raise HTTPException(status_code=404, detail="Meta não encontrada")

        if str(existing_goal.get("user_id")) != current_user.id:
            raise HTTPException(status_code=403, detail="Sem permissão para excluir esta meta")

        # Exclui a meta
        result = await goals_collection.delete_one({"_id": ObjectId(goal_id)})

        if result.deleted_count == 1:
            return {"mensagem": "Meta excluída com sucesso"}
        else:
            raise HTTPException(status_code=404, detail="Meta não encontrada")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao excluir meta: {str(e)}")

