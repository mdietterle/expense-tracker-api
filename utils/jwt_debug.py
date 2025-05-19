"""
Utilitário para diagnóstico de problemas com JWT.
Pode ser executado diretamente para verificar se um token é válido.
"""
import json
import sys
from jose import jwt, JWTError, ExpiredSignatureError
from datetime import datetime, timedelta
import logging

# Configurar logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# A mesma chave secreta que usamos no auth.py
SECRET_KEY = "0d4c5ec684efae716857cdf00b6319fcb6ec78bdbd7f8a1aa3d95c3ee493e775"
ALGORITHM = "HS256"

def decode_token(token: str, verify_expiration: bool = True):
    """
    Decodifica um token JWT e retorna seu payload.
    
    Args:
        token: O token JWT a ser decodificado
        verify_expiration: Se True, verifica se o token expirou
        
    Returns:
        dict: O payload do token decodificado
    """
    try:
        # Tenta decodificar o token com verificação de expiração
        options = {"verify_exp": verify_expiration}
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options=options)
        return {
            "status": "success",
            "payload": payload,
            "expired": False
        }
    except ExpiredSignatureError:
        # O token é válido, mas expirou
        try:
            # Decodificar sem verificar expiração
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
            exp_time = datetime.utcfromtimestamp(payload.get("exp", 0))
            now = datetime.utcnow()
            
            return {
                "status": "expired",
                "payload": payload,
                "expired": True,
                "expired_by": str(now - exp_time) if exp_time else "desconhecido"
            }
        except JWTError as e:
            return {
                "status": "error",
                "error": f"Erro ao decodificar token expirado: {str(e)}",
                "expired": True
            }
    except JWTError as e:
        # Erro na decodificação do token
        return {
            "status": "error",
            "error": f"Erro ao decodificar token: {str(e)}"
        }

def create_test_token(username: str, expire_in_minutes: int = 30):
    """
    Cria um token JWT de teste
    
    Args:
        username: O nome de usuário a incluir no token
        expire_in_minutes: Tempo de expiração em minutos
        
    Returns:
        str: Token JWT assinado
    """
    data = {"sub": username}
    expire = datetime.utcnow() + timedelta(minutes=expire_in_minutes)
    data.update({"exp": expire})
    
    token = jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)
    return token

if __name__ == "__main__":
    # Quando executado diretamente, testar um token
    if len(sys.argv) > 1:
        # Token fornecido como argumento
        token = sys.argv[1]
        print(f"Analisando token: {token[:15]}...")
        result = decode_token(token, verify_expiration=False)
        print(json.dumps(result, indent=2, default=str))
    else:
        # Gerar um token de teste
        test_username = "teste"
        test_token = create_test_token(test_username)
        print(f"Token de teste gerado para '{test_username}':")
        print(test_token)
        
        # Decodificar o token gerado
        print("\nDecodificação do token gerado:")
        result = decode_token(test_token)
        print(json.dumps(result, indent=2, default=str))
