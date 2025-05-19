# auth.py
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from typing import Optional, Dict, Any
from jose import JWTError, jwt, ExpiredSignatureError
from passlib.context import CryptContext
from models import User, TokenData, LoginRequest
from database import users_collection
import logging
import warnings
import os
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# Configurando logging para capturar detalhes do erro
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Silenciar avisos específicos do bcrypt no passlib
warnings.filterwarnings("ignore", message=".*error reading bcrypt version.*")

# Modifica o tokenUrl para usar /login em vez de /api/token para compatibilidade
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/login",
    auto_error=True
)

# Configuração para JWT - usando a chave do arquivo .env
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "0d4c5ec684efae716857cdf00b6319fcb6ec78bdbd7f8a1aa3d95c3ee493e775")
# Lista de chaves secretas alternativas para compatibilidade com tokens existentes
ALTERNATE_SECRET_KEYS = [
    "efae716857cdf00b6319fcb6ec78bdbd7f8a1aa3d95c3ee493e77",  # Chave usada pelo frontend para teste
    os.getenv("ALTERNATE_JWT_SECRET_KEY", ""),  # Chave alternativa do .env
    # Chave invertida (às vezes ocorre por razões estranhas)
    SECRET_KEY[::-1] if SECRET_KEY else "",
]
# Filtrar chaves vazias
ALTERNATE_SECRET_KEYS = [key for key in ALTERNATE_SECRET_KEYS if key]

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30  # 30 minutos
REFRESH_TOKEN_EXPIRE_DAYS = 7     # 7 dias

# Log da chave secreta sendo usada (apenas primeiros caracteres para segurança)
logger.info(f"Usando chave secreta principal (primeiros 10 caracteres): {SECRET_KEY[:10]}...")
for i, key in enumerate(ALTERNATE_SECRET_KEYS):
    if key:
        logger.info(f"Chave alternativa {i+1} disponível (primeiros 5 caracteres): {key[:5]}...")

# Armazenamento temporário de refresh tokens (em produção, usar Redis ou banco de dados)
refresh_tokens = {}

# Context para hash de senhas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    """Verifica se a senha em texto claro corresponde à senha hash"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    """Gera um hash para a senha fornecida"""
    return pwd_context.hash(password)

async def get_user(username: str):
    """Busca um usuário pelo nome de usuário"""
    if (user_doc := await users_collection.find_one({"username": username})):
        return User(
            id=str(user_doc["_id"]),
            username=user_doc["username"],
            password=user_doc["password"]
        )
    return None

async def authenticate_user(username: str, password: str):
    """Autentica um usuário verificando nome de usuário e senha"""
    user = await get_user(username)
    if not user:
        return None
    if not verify_password(password, user.password):
        return None
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Cria um novo token de acesso JWT"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict):
    """Cria um token de atualização com prazo mais longo"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    # Armazenar o token de atualização (em produção, usar banco de dados)
    username = data.get("sub")
    refresh_tokens[username] = encoded_jwt
    
    return encoded_jwt

def verify_token_with_multiple_keys(token: str):
    """
    Tenta verificar um token JWT com múltiplas chaves possíveis.
    Retorna o payload se uma das chaves funcionar.
    """
    logger.info(f"Verificando token: {token[:10]}...")  # Log do token recebido
    last_error = None
    
    # Primeiro tenta com a chave principal
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        logger.info("Token verificado com a chave principal")
        return payload
    except JWTError as e:
        last_error = e
        logger.warning(f"Falha na verificação com chave principal: {str(e)}")
    
    # Tenta com cada chave alternativa
    for i, alt_key in enumerate(ALTERNATE_SECRET_KEYS):
        try:
            payload = jwt.decode(token, alt_key, algorithms=[ALGORITHM])
            logger.info(f"Token verificado com chave alternativa {i+1}")
            return payload
        except JWTError as e:
            logger.warning(f"Falha na verificação com chave alternativa {i+1}: {str(e)}")
    
    # Se chegou aqui, nenhuma chave funcionou
    logger.error(f"Erro ao verificar token com múltiplas chaves: {last_error}")
    raise last_error

async def renew_access_token(refresh_token: str):
    """Renova um token de acesso usando o token de atualização"""
    try:
        # Tenta verificar com múltiplas chaves
        payload = verify_token_with_multiple_keys(refresh_token)
        username = payload.get("sub")
        
        if not username or refresh_tokens.get(username) != refresh_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de atualização inválido",
                headers={"WWW-Authenticate": "Bearer"}
            )
            
        # Criar novo token de acesso
        access_token = create_access_token(data={"sub": username})
        return {"access_token": access_token, "token_type": "bearer"}
        
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de atualização inválido",
            headers={"WWW-Authenticate": "Bearer"}
        )

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Obtém o usuário atual com base no token JWT fornecido"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não autorizado",
        headers={"WWW-Authenticate": "Bearer"}
    )
    
    try:
        # Tenta verificar o token com múltiplas chaves
        payload = verify_token_with_multiple_keys(token)
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username, exp=payload.get("exp"))
    except JWTError as e:
        logger.error(f"Erro JWT em get_current_user: {str(e)}")
        raise credentials_exception
        
    user = await get_user(username=token_data.username)
    if user is None:
        logger.error(f"Usuário não encontrado: {token_data.username}")
        raise credentials_exception
        
    return user

async def get_current_user_expired_ok(request: Request):
    """
    Versão adaptada de get_current_user que permite tokens expirados
    para manter compatibilidade com clientes existentes.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        logger.error("Authorization header ausente ou mal formatado")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token não fornecido",
            headers={"WWW-Authenticate": "Bearer"}
        )
        
    token = auth_header.replace("Bearer ", "")
    
    try:
        # Primeira tentativa: decodificar com verificação completa usando múltiplas chaves
        try:
            payload = verify_token_with_multiple_keys(token)
            username: str = payload.get("sub")
        except JWTError as e:
            logger.error(f"Erro ao verificar token com múltiplas chaves: {str(e)}")
            raise e
        
        if username is None:
            logger.error("Token não contém 'sub' claim")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Token inválido",
                headers={"WWW-Authenticate": "Bearer"}
            )
            
        token_data = TokenData(username=username, exp=payload.get("exp"))
        user = await get_user(username=token_data.username)
        
        if user is None:
            logger.error(f"Usuário não encontrado: {token_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuário não encontrado",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        return user
    except ExpiredSignatureError:
        # Token expirado, mas vamos permitir mesmo assim
        logger.info("Verificando token expirado: " + token[:10] + "...")
        
        # Tentamos cada chave possível ignorando a expiração
        last_error = None
        payload = None
        
        # Tenta a chave principal primeiro
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
            logger.info("Token expirado verificado com chave principal")
        except JWTError as e:
            last_error = e
            logger.warning(f"Falha na verificação com chave principal (ignorando expiração): {str(e)}")
        
        # Se falhou, tenta chaves alternativas
        if not payload:
            for i, alt_key in enumerate(ALTERNATE_SECRET_KEYS):
                try:
                    payload = jwt.decode(token, alt_key, algorithms=[ALGORITHM], options={"verify_exp": False})
                    logger.info(f"Token expirado verificado com chave alternativa {i+1}")
                    break
                except JWTError as e:
                    logger.warning(f"Falha na verificação com chave alternativa {i+1} (ignorando expiração): {str(e)}")
        
        # Se nenhuma chave funcionou
        if not payload:
            logger.error(f"Erro decodificando token (ignorando expiração): {last_error}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
        
        username: str = payload.get("sub")
        if username is None:
            logger.error("Token expirado não contém 'sub' claim")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
            
        user = await get_user(username=username)
        if user is None:
            logger.error(f"Usuário não encontrado (token expirado): {username}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")
            
        return user
    except JWTError as e:
        logger.error(f"Erro JWT: {str(e)}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    except Exception as e:
        logger.error(f"Erro inesperado em get_current_user_expired_ok: {str(e)}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autorizado")
