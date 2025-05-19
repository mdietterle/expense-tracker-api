from fastapi import APIRouter, HTTPException
from models import Expense, ExpenseCreate, ExpenseCategory
from database import expenses_collection, drivers_collection
from bson import ObjectId
from datetime import date, datetime
from auth import get_current_user, get_current_user_expired_ok
from fastapi import Depends

router = APIRouter()

def expense_helper(expense) -> dict:
    expense_dict = {
        "id": str(expense["_id"]),
        "user_id": expense.get("user_id", ""),
        "driver_id": expense["driver_id"],
        "trip_id": expense.get("trip_id"),
        "category": expense["category"],
        "amount": expense["amount"],
        "date": expense["date"],
        "description": expense["description"],
    }
    
    # Adicionar campos específicos para despesas de combustível
    if expense["category"] == ExpenseCategory.FUEL:
        expense_dict.update({
            "odometer": expense.get("odometer"),
            "fuel_type": expense.get("fuel_type"),
            "liters": expense.get("liters"),
            "price_per_liter": expense.get("price_per_liter")
        })
    
    return expense_dict

@router.post("/", response_model=Expense)
async def create_expense(expense: ExpenseCreate, current_user = Depends(get_current_user_expired_ok)):
    try:
        # Para versões mais recentes do Pydantic
        expense_dict = expense.model_dump()
    except AttributeError:
        # Para versões mais antigas do Pydantic
        expense_dict = expense.dict()
        
    expense_dict["user_id"] = current_user.id
    
    # Registrar driver_id original para depuração
    original_driver_id = expense_dict.get("driver_id")
    print(f"Criando despesa com driver_id original: {original_driver_id} (tipo: {type(original_driver_id)})")
    
    # Garantir que driver_id seja do tipo string (não ObjectId ou outro tipo)
    if "driver_id" in expense_dict and expense_dict["driver_id"] is not None:
        expense_dict["driver_id"] = str(expense_dict["driver_id"])
        print(f"Driver ID padronizado para string: {expense_dict['driver_id']}")
    
    # Garantir que amount seja float
    if "amount" in expense_dict:
        try:
            expense_dict["amount"] = float(expense_dict["amount"])
            print(f"Amount convertido para float: {expense_dict['amount']}")
        except (ValueError, TypeError):
            print(f"ERRO: Não foi possível converter amount para float")

    # Verificar se é despesa de combustível e validar campos específicos
    if expense_dict.get("category") == ExpenseCategory.FUEL:
        # Converter valores numéricos para float
        for field in ["odometer", "liters", "price_per_liter"]:
            if field in expense_dict and expense_dict[field] is not None:
                try:
                    expense_dict[field] = float(expense_dict[field])
                    print(f"{field.capitalize()} convertido para float: {expense_dict[field]}")
                except (ValueError, TypeError):
                    print(f"ERRO: Não foi possível converter {field} para float")
        
        # Verificar se os campos obrigatórios para combustível estão preenchidos
        if not all([
            expense_dict.get("odometer") is not None,
            expense_dict.get("fuel_type") is not None,
            expense_dict.get("liters") is not None,
            expense_dict.get("price_per_liter") is not None
        ]):
            print("Aviso: Despesa de combustível com campos incompletos")
            # Campos opcionais podem ser None, não geramos erro.

    # ✅ Converte date para datetime (adiciona meia-noite como hora)
    if isinstance(expense_dict.get("date"), date):
        expense_dict["date"] = datetime.combine(expense_dict["date"], datetime.min.time())

    new_expense = await expenses_collection.insert_one(expense_dict)
    created_expense = await expenses_collection.find_one({"_id": new_expense.inserted_id})
    return expense_helper(created_expense)

@router.post("", response_model=Expense)
async def create_expense_no_slash(expense: ExpenseCreate, current_user = Depends(get_current_user_expired_ok)):
    """Endpoint alternativo para criar despesa sem barra no final"""
    return await create_expense(expense, current_user)

@router.get("")
async def get_expenses():
    try:
        expenses = []
        async for expense in expenses_collection.find({}):
            try:
                expenses.append(expense_helper(expense))
            except KeyError as e:
                # Log do erro e continua sem adicionar o documento problemático
                print(f"Erro ao processar despesa {expense.get('_id')}: {str(e)}")
                continue
        return expenses
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar despesas: {str(e)}")

@router.get("/{expense_id}", response_model=Expense)
async def get_expense(expense_id: str):
    expense = await expenses_collection.find_one({"_id": ObjectId(expense_id)})
    if expense:
        return expense_helper(expense)
    raise HTTPException(status_code=404, detail="Despesa não encontrada")

@router.get("/driver/{driver_id}")
async def get_expenses_by_driver(driver_id: str):
    print(f"Buscando despesas para driver_id: {driver_id}")
    
    def ids_sao_similares(id1, id2):
        """Verifica se dois IDs representam provavelmente o mesmo motorista"""
        if id1 is None or id2 is None:
            return False
            
        # Converter ambos para string para comparação
        id1_str = str(id1).lower().strip()
        id2_str = str(id2).lower().strip()
        
        # Verificar se são iguais após normalização
        if id1_str == id2_str:
            return True
            
        # Verificar se um contém o outro completamente (substring)
        if id1_str in id2_str or id2_str in id1_str:
            return True
            
        # Verificar se um é representação numérica do outro
        try:
            if id1_str.isdigit() and id2_str == id1_str:
                return True
        except:
            pass
            
        return False
    
    # Estratégia 1: Verificar variações óbvias
    consulta_basica = {
        "$or": [
            {"driver_id": driver_id},
            {"driver_id": driver_id.strip()},
            {"driver_id": driver_id.lower()},
            {"driver_id": driver_id.upper()},
            {"driver_id": str(driver_id)}
        ]
    }
    
    # Buscar despesas primeiro com consulta básica
    expenses = []
    async for expense in expenses_collection.find(consulta_basica):
        print(f"Despesa encontrada (consulta básica): ID={expense.get('_id')} driver_id={expense.get('driver_id')}")
        expenses.append(expense_helper(expense))
    
    # Se não encontrou nada, tenta estratégia mais agressiva
    if not expenses:
        print("Nenhuma despesa encontrada na consulta básica. Tentando estratégia avançada...")
        # Busca todas as despesas e filtra manualmente
        todas_despesas = await expenses_collection.find({}).to_list(length=None)
        print(f"Total de despesas no banco: {len(todas_despesas)}")
        
        for expense in todas_despesas:
            expense_driver_id = expense.get("driver_id")
            if ids_sao_similares(expense_driver_id, driver_id):
                print(f"Match encontrado: despesa {expense['_id']} com driver_id '{expense_driver_id}'")
                expenses.append(expense_helper(expense))
    
    print(f"Total de despesas encontradas: {len(expenses)}")
    return expenses

@router.get("/normalize/{driver_id}")
async def normalize_expenses_driver_id(driver_id: str, current_user = Depends(get_current_user)):
    """Normaliza o driver_id nas despesas existentes"""
    print(f"Normalizando driver_id '{driver_id}' nas despesas...")
    
    # Encontrar todas as variações deste driver_id
    all_expenses = await expenses_collection.find({}).to_list(length=None)
    variantes_encontradas = []
    
    for expense in all_expenses:
        expense_driver_id = expense.get("driver_id")
        # Verificar se este ID é uma variante do driver_id fornecido
        if expense_driver_id and (str(expense_driver_id).lower().strip() == str(driver_id).lower().strip()):
            if expense_driver_id != driver_id and expense_driver_id not in variantes_encontradas:
                variantes_encontradas.append(expense_driver_id)
    
    # Atualizar todas as variantes para o ID normalizado
    resultados = []
    for variante in variantes_encontradas:
        resultado = await expenses_collection.update_many(
            {"driver_id": variante},
            {"$set": {"driver_id": driver_id}}
        )
        resultados.append({
            "de": variante,
            "para": driver_id,
            "atualizados": resultado.modified_count
        })
    
    return {
        "driver_id_normalizado": driver_id,
        "variantes_encontradas": variantes_encontradas,
        "resultados": resultados
    }


@router.put("/{expense_id}")
async def update_expense(expense_id: str, expense_data: ExpenseCreate,
                         current_user=Depends(get_current_user_expired_ok)):
    """Atualiza uma despesa existente"""
    try:
        # Verifica se a despesa existe e pertence ao usuário
        existing_expense = await expenses_collection.find_one({"_id": ObjectId(expense_id)})
        if not existing_expense:
            raise HTTPException(status_code=404, detail="Despesa não encontrada")

        if str(existing_expense.get("user_id")) != current_user.id:
            raise HTTPException(status_code=403, detail="Sem permissão para atualizar esta despesa")

        # Prepara os dados para atualização
        try:
            update_data = expense_data.model_dump()
        except AttributeError:
            update_data = expense_data.dict()

        update_data["user_id"] = current_user.id

        # Garante que driver_id seja string
        if "driver_id" in update_data:
            update_data["driver_id"] = str(update_data["driver_id"])

        # Converte valores numéricos para float
        if "amount" in update_data:
            update_data["amount"] = float(update_data["amount"])

        # Trata campos específicos para despesas de combustível
        if update_data.get("category") == ExpenseCategory.FUEL:
            for field in ["odometer", "liters", "price_per_liter"]:
                if field in update_data and update_data[field] is not None:
                    update_data[field] = float(update_data[field])

        # Converte date para datetime
        if isinstance(update_data.get("date"), date):
            update_data["date"] = datetime.combine(update_data["date"], datetime.min.time())

        # Atualiza a despesa
        await expenses_collection.update_one(
            {"_id": ObjectId(expense_id)},
            {"$set": update_data}
        )

        # Retorna a despesa atualizada
        updated_expense = await expenses_collection.find_one({"_id": ObjectId(expense_id)})
        return expense_helper(updated_expense)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar despesa: {str(e)}")


@router.delete("/{expense_id}")
async def delete_expense(expense_id: str, current_user=Depends(get_current_user_expired_ok)):
    """Exclui uma despesa específica"""
    try:
        # Verifica se a despesa existe e pertence ao usuário
        existing_expense = await expenses_collection.find_one({"_id": ObjectId(expense_id)})
        if not existing_expense:
            raise HTTPException(status_code=404, detail="Despesa não encontrada")

        if str(existing_expense.get("user_id")) != current_user.id:
            raise HTTPException(status_code=403, detail="Sem permissão para excluir esta despesa")

        # Exclui a despesa
        result = await expenses_collection.delete_one({"_id": ObjectId(expense_id)})

        if result.deleted_count == 1:
            return {"mensagem": "Despesa excluída com sucesso"}
        else:
            raise HTTPException(status_code=404, detail="Despesa não encontrada")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao excluir despesa: {str(e)}")
