from loguru import logger


class UploadFailed(Exception): pass
class CommandRequiresAdmin(Exception): pass
class CommandRequiresOwner(Exception): pass
class MatrixBotError(Exception): pass
class AuthenticationError(MatrixBotError): pass
class NetworkError(MatrixBotError): pass


def handle_error_response(
        response: int
) -> None:
    if response.status_code == 401:
        logger.error("Access token is invalid or missing!")
        logger.info("Check your MATRIX_ACCESS_TOKEN.")

        raise AuthenticationError("Invalid token")
        
    elif response.status_code >= 500:
        logger.warning(f"Server error: {response.status_code}")
        raise NetworkError(f"Server side issue: {response.status_code}")