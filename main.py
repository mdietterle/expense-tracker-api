from fastapi import Depends, FastAPI, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from jose import jwt, ExpiredSignatureError, JWTError
from datetime import datetime, timedelta

from database import users_collection, normalize_driver_ids, merge_driver_ids
from models import LoginRequest, User, TokenResponse, UserCreate
from auth import authenticate_user, create_access_token, create_refresh_token, get_user, get_password_hash, get_current_user, renew_access_token
from routes import drivers, trips, expenses, goals, reports
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
import logging
from auth import SECRET_KEY, ALGORITHM, ALTERNATE_SECRET_KEYS, verify_token_with_multiple_keys
import traceback
from models import UserUpdate
from bson import ObjectId

# Configurar logger para depuração
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Log da chave secreta sendo utilizada (apenas primeiros caracteres para segurança)
logger.info(f"Aplicação principal usando chave secreta (primeiros 10 caracteres): {SECRET_KEY[:10]}...")

# Configuração de manipulador de logs para arquivo
file_handler = logging.FileHandler('api.log')
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Configuração atualizada do CORS para garantir que os cabeçalhos estejam presentes mesmo em erros
app = FastAPI(middleware=[
        Middleware(TrustedHostMiddleware, allowed_hosts=["*"])
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite todas as origens
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Token-Expired", "WWW-Authenticate"]  # Expor cabeçalhos personalizados
)

# Middleware para verificar tokens antes de processar a requisição
@app.middleware("http")
async def token_verification_middleware(request: Request, call_next):
    """
    Middleware para verificar e possivelmente aceitar tokens expirados 
    para determinadas rotas.
    """

    # Excluir endpoints que não exigem token
    if request.url.path in ["/api/login", "/api/register", "/api/refresh-token"]:
        return await call_next(request)


    logger.info(f"Recebida requisição: {request.method} {request.url}")
    logger.info(f"Headers da requisição: {request.headers}")

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        logger.info(f"Authorization header presente: {auth_header[:15]}...")
        token = auth_header.replace("Bearer ", "")

        try:
            # Tentar validação com múltiplas chaves, ignorando expiração para diagnóstico
            for i, key in enumerate([SECRET_KEY] + ALTERNATE_SECRET_KEYS):
                try:
                    # Decodificar o token sem verificar expiração para depuração
                    payload = jwt.decode(token, key, algorithms=[ALGORITHM], options={"verify_exp": False})
                    key_info = "principal" if i == 0 else f"alternativa {i}"
                    logger.info(f"Token decodificado com sucesso usando chave {key_info}: {payload}")
                    
                    # Tentar verificar com expiração usando a mesma chave que funcionou
                    try:
                        jwt.decode(token, key, algorithms=[ALGORITHM])
                        logger.info(f"Token válido e não expirado (usando chave {key_info})")
                        # Token válido, não precisamos verificar mais chaves
                        break
                    except ExpiredSignatureError:
                        logger.warning(f"Token expirado (chave {key_info}).")
                        request.state.token_expired = True
                        # Token expirado, mas decodificável, não precisamos verificar mais chaves
                        break
                except JWTError as e:
                    if i == len(ALTERNATE_SECRET_KEYS):
                        # Se foi a última chave e ainda falhou
                        logger.error(f"Erro ao verificar token JWT com todas as chaves: {str(e)}")
                    # Senão, continua testando outras chaves
                    continue
        except Exception as e:
            logger.error(f"Erro inesperado ao processar token: {str(e)}")
    else:
        logger.warning("Authorization header ausente ou inválido.")

    response = await call_next(request)

    if response.status_code == 401 and getattr(request.state, "token_expired", False):
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Token expirado, renove usando /api/refresh-token",
                "token_expired": True,
            },
            headers={"WWW-Authenticate": "Bearer"}
        )

    return response

# Registrar rotas
app.include_router(drivers.router, prefix="/api/me", tags=["me"])
app.include_router(drivers.router, prefix="/api/drivers", tags=["drivers"])
app.include_router(trips.router, prefix="/api/trips", tags=["trips"])
app.include_router(expenses.router, prefix="/api/expenses", tags=["expenses"])
app.include_router(goals.router, prefix="/api/goals", tags=["goals"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])

# Endpoint para login
@app.post("/api/login", response_model=TokenResponse)
async def login(login_data: LoginRequest):
    user = await authenticate_user(login_data.username, login_data.password)
    if not user:
        logger.warning(f"Tentativa de login falhou para usuário: {login_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nome de usuário ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    logger.info(f"Login bem-sucedido para usuário: {login_data.username}")
    
    # Gerar token de acesso
    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    # Gerar token de atualização
    refresh_token = create_refresh_token(data={"sub": user.username})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
        "user_id": user.id
    }

@app.post("/api/refresh-token")
async def refresh_token_endpoint(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de atualização não fornecido",
            headers={"WWW-Authenticate": "Bearer"}
        )
        
    refresh_token = auth_header.replace("Bearer ", "")
    try:
        # Tenta verificar o token de atualização com múltiplas chaves
        for key in [SECRET_KEY] + ALTERNATE_SECRET_KEYS:
            try:
                payload = jwt.decode(refresh_token, key, algorithms=[ALGORITHM])
                username = payload.get("sub")
                
                if not username:
                    continue
                
                # Token válido, gerar novo token de acesso
                access_token = create_access_token(data={"sub": username})
                logger.info(f"Token renovado com sucesso para: {username}")
                return {"access_token": access_token, "token_type": "bearer"}
            except JWTError:
                continue
        
        # Se chegou aqui, nenhuma chave funcionou
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de atualização inválido",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except Exception as e:
        logger.error(f"Erro ao renovar token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao processar solicitação de renovação de token"
        )

# Endpoint para criar um novo usuário
@app.post("/api/register", response_model=User)
async def create_user(user: UserCreate):
    # Verificar se o usuário já existe
    existing_user = await users_collection.find_one({"username": user.username})
    if existing_user:
        logger.warning(f"Tentativa de criar usuário existente: {user.username}")
        raise HTTPException(status_code=400, detail="Nome de usuário já está em uso")
    
    # Criar hash da senha
    hashed_password = get_password_hash(user.password)
    user_dict = user.dict()
    user_dict["password"] = hashed_password
    
    # Inserir novo usuário
    result = await users_collection.insert_one(user_dict)
    
    # Recuperar o usuário criado
    created_user = await users_collection.find_one({"_id": result.inserted_id})
    
    logger.info(f"Novo usuário criado: {user.username}")
    return User(
        id=str(created_user["_id"]),
        username=created_user["username"],
        password=created_user["password"]  # A senha já está com hash
    )

# Endpoint para verificar a autenticação do usuário atual
@app.get("/api/me", response_model=User)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

# Endpoint para normalizar IDs de motoristas no banco de dados
@app.post("/api/admin/normalize-driver-ids")
async def normalize_driver_ids_endpoint(current_user: User = Depends(get_current_user)):
    # Aqui poderíamos adicionar uma verificação se o usuário é um administrador
    result = await normalize_driver_ids()
    return result

# Endpoint para mesclar IDs de motoristas
@app.post("/api/admin/merge-driver-ids")
async def merge_driver_ids_endpoint(data: dict, current_user: User = Depends(get_current_user)):
    # Verificar se os campos necessários estão presentes
    if "source_id" not in data or "target_id" not in data:
        raise HTTPException(status_code=400, detail="source_id e target_id são obrigatórios")
    
    # Chamar a função para mesclar IDs
    result = await merge_driver_ids(data["source_id"], data["target_id"])
    return result

# Adicionar um endpoint para debug da chave secreta
@app.get("/api/debug/token-info", include_in_schema=False)
async def debug_token_info(request: Request):
    """Endpoint para depuração de tokens (apenas ambiente de desenvolvimento)"""
    auth_header = request.headers.get("Authorization")
    
    if not auth_header or not auth_header.startswith("Bearer "):
        return {"error": "Token não fornecido"}
    
    token = auth_header.replace("Bearer ", "")
    results = []
    
    # Tentar com a chave principal
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
        exp = payload.get("exp")
        now = datetime.utcnow().timestamp()
        results.append({
            "key": "principal",
            "key_preview": SECRET_KEY[:5] + "...",
            "success": True,
            "payload": payload,
            "exp": exp,
            "is_expired": exp and exp < now,
            "time_remaining": exp - now if exp and exp >= now else None
        })
    except Exception as e:
        results.append({
            "key": "principal",
            "key_preview": SECRET_KEY[:5] + "...",
            "success": False,
            "error": str(e)
        })
    
    # Tentar com chaves alternativas
    for i, alt_key in enumerate(ALTERNATE_SECRET_KEYS):
        try:
            payload = jwt.decode(token, alt_key, algorithms=[ALGORITHM], options={"verify_exp": False})
            exp = payload.get("exp")
            now = datetime.utcnow().timestamp()
            results.append({
                "key": f"alternativa_{i+1}",
                "key_preview": alt_key[:5] + "...",
                "success": True,
                "payload": payload,
                "exp": exp,
                "is_expired": exp and exp < now,
                "time_remaining": exp - now if exp and exp >= now else None
            })
        except Exception as e:
            results.append({
                "key": f"alternativa_{i+1}",
                "key_preview": alt_key[:5] + "...",
                "success": False,
                "error": str(e)
            })
    
    return {
        "token_preview": token[:10] + "...",
        "results": results,
        "current_time": datetime.utcnow().timestamp()
    }

# No arquivo main.py, adicione:

@app.get("/api/users/me", response_model=User)
async def get_user_profile(current_user = Depends(get_current_user)):
    """Retorna os dados do perfil do usuário atual"""
    user = await users_collection.find_one({"_id": ObjectId(current_user.id)})
    if user:
        return {
            "id": str(user["_id"]),
            "username": user["username"],
            "email": user["email"],
            "profile_picture": user.get("profile_picture", ""), # Campo opcional
            "created_at": user.get("created_at", datetime.utcnow()),
            "updated_at": user.get("updated_at", datetime.utcnow())
        }
    raise HTTPException(status_code=404, detail="Usuário não encontrado")

@app.put("/api/users/me", response_model=User)
async def update_user_profile(
        user_data: UserUpdate,
        current_user: User = Depends(get_current_user)
):
    try:
        update_data = user_data.dict(exclude_unset=True)

        # Não permitir alteração de senha através desta rota
        if "password" in update_data:
            del update_data["password"]

        result = await users_collection.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": update_data}
        )

        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        updated_user = await users_collection.find_one(
            {"_id": ObjectId(current_user.id)}
        )
        return User(
            id=str(updated_user["_id"]),
            username=updated_user["username"],
            email=updated_user.get("email", ""),
            profile_picture=updated_user.get("profile_picture", "")
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao atualizar perfil: {str(e)}"
        )
