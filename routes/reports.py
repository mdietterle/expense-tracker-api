from fastapi import APIRouter, HTTPException, Header
from fastapi import Depends, Request, status
from auth import get_current_user, oauth2_scheme, jwt, SECRET_KEY, ALGORITHM, get_current_user_expired_ok
from models import ReportBase
from database import reports_collection, trips_collection, expenses_collection, goals_collection
from datetime import date, datetime
from bson import ObjectId
import logging
from jose import JWTError, ExpiredSignatureError
import json

# Configurar logger para depuração
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter()

def report_helper(report) -> dict:
    # Certifica-se de que os valores numéricos são tratados adequadamente
    total_earnings = float(report.get("total_earnings", 0.0))
    total_expenses = float(report.get("total_expenses", 0.0))
    
    # Calcula o lucro líquido
    net_profit = total_earnings - total_expenses
    
    # Garantir que as datas são do tipo date para corresponder ao modelo ReportBase
    period_start = report["period_start"]
    if isinstance(period_start, datetime):
        period_start = period_start.date()
    
    period_end = report["period_end"]
    if isinstance(period_end, datetime):
        period_end = period_end.date()
    
    return {
        "id": str(report["_id"]),
        "user_id": report.get("user_id", ""),  # Valor padrão vazio se não existir
        "driver_id": report["driver_id"],
        "period_start": period_start,
        "period_end": period_end,
        "total_earnings": total_earnings,
        "total_expenses": total_expenses,
        "net_profit": net_profit,  # Incluindo explicitamente o campo net_profit
        "goals_progress": report.get("goals_progress", {})
    }

async def process_report_request(data: dict, current_user):
    """
    Função de utilidade para processar solicitações de relatório
    Compartilhada entre os endpoints com e sem barra
    """
    logger.info(f"Dados recebidos: {json.dumps(data)}")
    
    driver_id = data.get("driver_id")
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    if not all([driver_id, start_date, end_date]):
        logger.error("Dados incompletos para o relatório.")
        raise HTTPException(status_code=400, detail="Dados incompletos para o relatório")

    # Converter strings para datetime
    try:
        start_date_dt = datetime.fromisoformat(start_date)
        end_date_dt = datetime.fromisoformat(end_date)
    except ValueError as e:
        logger.error(f"Erro ao converter datas: {e}")
        raise HTTPException(status_code=400, detail="Formato de data inválido")

    # Ajustar fim do dia para end_date
    query_end_date = datetime.combine(end_date_dt.date(), datetime.max.time())

    # Consultar ganhos e despesas
    total_earnings = await trips_collection.aggregate([
        {"$match": {"driver_id": driver_id, "date": {"$gte": start_date_dt, "$lte": query_end_date}}},
        {"$group": {"_id": None, "total": {"$sum": "$earnings"}}}
    ]).to_list(length=1)

    total_expenses = await expenses_collection.aggregate([
        {"$match": {"driver_id": driver_id, "date": {"$gte": start_date_dt, "$lte": query_end_date}}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]).to_list(length=1)

    total_earnings = total_earnings[0]["total"] if total_earnings else 0.0
    total_expenses = total_expenses[0]["total"] if total_expenses else 0.0
    net_profit = total_earnings - total_expenses

    logger.info(f"Ganhos totais: {total_earnings}, Despesas totais: {total_expenses}, Lucro líquido: {net_profit}")

    # Consultar metas
    goals_cursor = goals_collection.find({"driver_id": driver_id})
    goals = await goals_cursor.to_list(length=None)
    goals_progress = {
        str(goal["_id"]): {
            "name": goal["name"],
            "progress": min((net_profit / goal["target_amount"]) * 100, 100) if goal["target_amount"] > 0 else 0
        }
        for goal in goals
    }

    # Criar relatório
    report_data = {
        "user_id": current_user.id,
        "driver_id": driver_id,
        "period_start": start_date_dt,
        "period_end": end_date_dt,
        "total_earnings": total_earnings,
        "total_expenses": total_expenses,
        "net_profit": net_profit,
        "goals_progress": goals_progress
    }

    new_report = await reports_collection.insert_one(report_data)
    created_report = await reports_collection.find_one({"_id": new_report.inserted_id})

    logger.info("Relatório gerado com sucesso.")
    return report_helper(created_report)

# Endpoint com a barra final
@router.post("/", response_model=ReportBase)
async def generate_report(data: dict, current_user=Depends(get_current_user_expired_ok)):
    """
    Gera um relatório para o motorista especificado no período fornecido.
    """
    logger.info("Iniciando geração de relatório (endpoint com barra).")
    return await process_report_request(data, current_user)

# Endpoint sem a barra final
@router.post("", response_model=ReportBase)
async def generate_report_no_slash(data: dict, current_user=Depends(get_current_user_expired_ok)):
    """
    Endpoint alternativo para criar relatório sem barra no final
    """
    logger.info("Iniciando geração de relatório (endpoint sem barra).")
    return await process_report_request(data, current_user)

@router.get("/driver/{driver_id}")
async def get_reports_by_driver(driver_id: str, current_user = Depends(get_current_user)):
    try:
        reports = []
        # Imprimir o driver_id para verificar o valor recebido
        print(f"Buscando relatórios para driver_id: {driver_id}")
        
        cursor = reports_collection.find({"driver_id": driver_id})
        reports_count = 0
        
        async for report in cursor:
            reports_count += 1
            try:
                reports.append(report_helper(report))
            except Exception as e:
                print(f"Erro ao processar relatório {report.get('_id')}: {str(e)}")
                continue
        
        print(f"Total de relatórios encontrados: {reports_count}")
        return reports
    except Exception as e:
        print(f"Erro na busca de relatórios: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Erro ao buscar relatórios para o motorista {driver_id}: {str(e)}"
        )


@router.get("/{report_id}")
async def get_report(report_id: str, current_user = Depends(get_current_user)):
    report = await reports_collection.find_one({"_id": ObjectId(report_id)})
    if report:
        return report_helper(report)
    raise HTTPException(status_code=404, detail="Relatório não encontrado")


@router.post("/verify-data")
async def verify_report_data(data: dict, current_user = Depends(get_current_user)):
    """Endpoint para verificar se existem dados no período para o motorista selecionado"""
    driver_id = data.get("driver_id")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    
    if not all([driver_id, start_date, end_date]):
        raise HTTPException(status_code=400, detail="Dados incompletos para verificação")
    
    # Armazenar datas originais como date para a resposta
    original_start_date = None
    original_end_date = None
    
    # Converter strings para datetime para consultas
    if isinstance(start_date, str):
        try:
            start_date_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            original_start_date = start_date_dt.date()
        except ValueError:
            start_date_dt = datetime.strptime(start_date, "%Y-%m-%d")
            original_start_date = start_date_dt.date()
    elif isinstance(start_date, date):
        original_start_date = start_date if not isinstance(start_date, datetime) else start_date.date()
        start_date_dt = datetime.combine(start_date, datetime.min.time())
    else:
        raise HTTPException(status_code=400, detail=f"Formato de data inicial inválido: {start_date}")

    if isinstance(end_date, str):
        try:
            end_date_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            original_end_date = end_date_dt.date()
        except ValueError:
            end_date_dt = datetime.strptime(end_date, "%Y-%m-%d")
            original_end_date = end_date_dt.date()
    elif isinstance(end_date, date):
        original_end_date = end_date if not isinstance(end_date, datetime) else end_date.date()
        end_date_dt = datetime.combine(end_date, datetime.min.time())
    else:
        raise HTTPException(status_code=400, detail=f"Formato de data final inválido: {end_date}")
    
    # Ajustar fim do dia para end_date
    query_end_date = datetime.combine(end_date_dt.date(), datetime.max.time())
    
    # Verificar viagens
    trips_count = await trips_collection.count_documents({
        "driver_id": driver_id,
        "date": {"$gte": start_date_dt, "$lte": query_end_date}
    })
    
    # Verificar despesas
    expenses_count = await expenses_collection.count_documents({
        "driver_id": driver_id,
        "date": {"$gte": start_date_dt, "$lte": query_end_date}
    })
    
    # Usar os objetos date para a resposta
    return {
        "has_data": trips_count > 0 or expenses_count > 0,
        "trips_count": trips_count,
        "expenses_count": expenses_count,
        "driver_id": driver_id,
        "period": {
            "start": original_start_date.isoformat(),
            "end": original_end_date.isoformat()
        }
    }

