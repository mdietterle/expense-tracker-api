from bson import ObjectId
from pydantic import BaseModel, EmailStr
from datetime import datetime, date
from enum import Enum
from typing import Optional, List, Dict, Any, Union

# Modelo de usuário
# No arquivo models.py

class UserBase(BaseModel):
    username: str
    email: str = ""
    profile_picture: str = ""

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    """Modelo para atualização de dados do usuário"""
    username: str | None = None
    email: EmailStr | None = None
    profile_picture: str | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "username": "john_doe",
                "email": "john@example.com",
                "profile_picture": "https://example.com/photo.jpg"
            }
        }

class User(BaseModel):
    """Modelo completo do usuário com todos os campos"""
    id: str
    username: str
    email: EmailStr
    profile_picture: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "username": "joao_silva",
                "email": "joao@exemplo.com",
                "profile_picture": "https://exemplo.com/foto.jpg",
                "created_at": "2024-03-20T10:00:00",
                "updated_at": "2024-03-20T10:00:00"
            }
        }

class DriverBase(BaseModel):
    name: str
    password: str

class TokenData(BaseModel):
    username: Optional[str] = None
    exp: datetime

# Modelo de login
class LoginRequest(BaseModel):
    username: str
    password: str

# Modelo de resposta de token
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: Optional[str] = None
    refresh_token: Optional[str] = None

class DriverCreate(DriverBase):
    pass

class Driver(DriverBase):
    id: str

class TripBase(BaseModel):
    user_id: str
    driver_id: str
    platform: str
    date: date
    distance: float
    earnings: float
    origin: str  # Novo campo
    destination: str  # Novo campo

class TripCreate(BaseModel):
    driver_id: str
    platform: str
    date: date
    distance: float
    earnings: float
    origin: str
    destination: str

    def to_mongo(self):
        data = self.model_dump()
        # Converte date para datetime
        data["date"] = datetime.combine(self.date, datetime.min.time())
        return data

class Trip(TripBase):
    id: str

class ExpenseCategory(str, Enum):
    FUEL = "Combustível"
    MAINTENANCE = "Manutenção"
    TAXES = "Impostos"
    INSURANCE = "Seguro"
    OTHER = "Outros"

class FuelType(str, Enum):
    GASOLINE = "Gasolina"
    ETHANOL = "Etanol"
    DIESEL = "Diesel"
    CNG = "GNV"  # Gás Natural Veicular
    FLEX = "Flex"  # Mistura

class ExpenseBase(BaseModel):
    user_id: str
    driver_id: str
    trip_id: Optional[str] = None
    category: ExpenseCategory
    amount: float
    date: datetime
    description: str
    # Campos específicos para despesas de combustível
    odometer: Optional[float] = None  # Quilometragem do veículo
    fuel_type: Optional[FuelType] = None  # Tipo de combustível
    liters: Optional[float] = None  # Quantidade de litros
    price_per_liter: Optional[float] = None  # Preço por litro

class ExpenseCreate(ExpenseBase):
    pass

class Expense(ExpenseBase):
    id: str

class GoalBase(BaseModel):
    user_id: Optional[str] = None
    driver_id: str
    name: str
    target_amount: float
    deadline: date

class GoalCreate(GoalBase):
    pass

class Goal(GoalBase):
    id: str
    current_amount: float = 0.0

class ReportBase(BaseModel):
    user_id: str
    driver_id: str
    period_start: date
    period_end: date
    total_earnings: float
    total_expenses: float
    net_profit: float = 0.0  # Adicionado o campo net_profit com valor default 0
    goals_progress: Dict[str, dict]

class ReportCreate(ReportBase):
    pass

class Report(ReportBase):
    id: str

