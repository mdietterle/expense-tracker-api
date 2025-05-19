from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorCollection
from datetime import datetime
from datetime import date

import os

load_dotenv()

MONGO_DETAILS = os.getenv("MONGO_URI", "mongodb://root:example@mongo:27017/")

client = AsyncIOMotorClient(MONGO_DETAILS)

database = client.expense_tracker

drivers_collection = database.get_collection("drivers")
trips_collection = database.get_collection("trips")
expenses_collection = database.get_collection("expenses")
goals_collection = database.get_collection("goals")
reports_collection = database.get_collection("reports")
users_collection = database.get_collection("users")

def convert_date(date_str: str) -> date:
    return datetime.fromisoformat(date_str).date()
    
async def normalize_driver_ids():
    """Função para normalizar driver_ids em todas as coleções do banco de dados.
    
    Esta função pode ser chamada para corrigir inconsistências em IDs de motoristas.
    Todos os IDs são convertidos para string para garantir consistência.
    """
    print("Iniciando normalização de driver_ids em todas as coleções...")
    
    # Processar trips
    trip_counter = 0
    async for trip in trips_collection.find({}):
        original_id = trip.get("driver_id")
        if original_id is not None:
            normalized_id = str(original_id).strip()
            if normalized_id != original_id:
                trip_counter += 1
                await trips_collection.update_one(
                    {"_id": trip["_id"]},
                    {"$set": {"driver_id": normalized_id}}
                )
    
    # Processar expenses
    expense_counter = 0
    async for expense in expenses_collection.find({}):
        original_id = expense.get("driver_id")
        if original_id is not None:
            normalized_id = str(original_id).strip()
            if normalized_id != original_id:
                expense_counter += 1
                await expenses_collection.update_one(
                    {"_id": expense["_id"]},
                    {"$set": {"driver_id": normalized_id}}
                )
    
    # Processar goals
    goal_counter = 0
    async for goal in goals_collection.find({}):
        original_id = goal.get("driver_id")
        if original_id is not None:
            normalized_id = str(original_id).strip()
            if normalized_id != original_id:
                goal_counter += 1
                await goals_collection.update_one(
                    {"_id": goal["_id"]},
                    {"$set": {"driver_id": normalized_id}}
                )
    
    # Processar reports
    report_counter = 0
    async for report in reports_collection.find({}):
        original_id = report.get("driver_id")
        if original_id is not None:
            normalized_id = str(original_id).strip()
            if normalized_id != original_id:
                report_counter += 1
                await reports_collection.update_one(
                    {"_id": report["_id"]},
                    {"$set": {"driver_id": normalized_id}}
                )
    
    print(f"Normalização concluída. Registros atualizados:")
    print(f"  - Viagens: {trip_counter}")
    print(f"  - Despesas: {expense_counter}")
    print(f"  - Metas: {goal_counter}")
    print(f"  - Relatórios: {report_counter}")
    
    return {
        "trips_updated": trip_counter,
        "expenses_updated": expense_counter,
        "goals_updated": goal_counter,
        "reports_updated": report_counter
    }
    
async def merge_driver_ids(source_id, target_id):
    """Função para mesclar dois IDs de motorista, atualizando todos os registros
    do source_id para target_id em todas as coleções.
    
    Args:
        source_id: ID que será substituído
        target_id: ID que substituirá o source_id
    """
    if not source_id or not target_id:
        return {"error": "IDs de origem e destino são obrigatórios"}
    
    # Normalizar IDs
    source_id = str(source_id).strip()
    target_id = str(target_id).strip()
    
    print(f"Mesclando driver_id '{source_id}' para '{target_id}'...")
    
    # Atualizar trips
    trip_result = await trips_collection.update_many(
        {"driver_id": source_id},
        {"$set": {"driver_id": target_id}}
    )
    
    # Atualizar expenses
    expense_result = await expenses_collection.update_many(
        {"driver_id": source_id},
        {"$set": {"driver_id": target_id}}
    )
    
    # Atualizar goals
    goal_result = await goals_collection.update_many(
        {"driver_id": source_id},
        {"$set": {"driver_id": target_id}}
    )
    
    # Atualizar reports
    report_result = await reports_collection.update_many(
        {"driver_id": source_id},
        {"$set": {"driver_id": target_id}}
    )
    
    print(f"Mesclagem concluída. Registros atualizados:")
    print(f"  - Viagens: {trip_result.modified_count}")
    print(f"  - Despesas: {expense_result.modified_count}")
    print(f"  - Metas: {goal_result.modified_count}")
    print(f"  - Relatórios: {report_result.modified_count}")
    
    return {
        "trips_updated": trip_result.modified_count,
        "expenses_updated": expense_result.modified_count,
        "goals_updated": goal_result.modified_count,
        "reports_updated": report_result.modified_count
    }