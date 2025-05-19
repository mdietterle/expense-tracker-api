from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
from jose import jwt, ExpiredSignatureError
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class TokenExpirationMiddleware(BaseHTTPMiddleware):
    """
    Middleware para detectar proativamente tokens prestes a expirar e
    adicionar um cabeçalho especial para informar o cliente.
    """
    
    def __init__(self, app, secret_key: str, algorithm: str = "HS256", expiry_window_minutes: int = 30):
        super().__init__(app)
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.expiry_window = timedelta(minutes=expiry_window_minutes)
    
    async def dispatch(self, request: Request, call_next):
        # Verificar se é uma requisição com token
        auth_header = request.headers.get("Authorization")
        
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            
            try:
                # Decodificar token sem verificar expiração
                payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm], options={"verify_exp": False})
                
                # Verificar se está próximo de expirar
                if "exp" in payload:
                    exp_timestamp = payload["exp"]
                    exp_datetime = datetime.fromtimestamp(exp_timestamp)
                    
                    # Se estiver prestes a expirar nos próximos X minutos
                    if exp_datetime - datetime.utcnow() < self.expiry_window:
                        logger.info(f"Token próximo de expirar para usuário: {payload.get('sub')}")
                        
                        # Preparar uma resposta com cabeçalho especial
                        response = await call_next(request)
                        response.headers["X-Token-Expiring-Soon"] = "true"
                        return response
                    
                    # Já expirou
                    if exp_datetime < datetime.utcnow():
                        logger.warning(f"Token já expirado para usuário: {payload.get('sub')}")
                
            except ExpiredSignatureError:
                # Token já expirou - deixar isso ser tratado pela aplicação principal
                pass
            except Exception as e:
                # Erro ao processar token - logar mas não interferir
                logger.error(f"Erro ao analisar token: {str(e)}")
        
        # Prosseguir normalmente se não houver alterações
        response = await call_next(request)
        return response
