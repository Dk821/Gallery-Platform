from fastapi import HTTPException


class ApiError(HTTPException):
    """
    Raise this anywhere in the app instead of a bare HTTPException.
    The exception handler in main.py turns it into:
      { "success": false, "error": { "code": ..., "message": ... } }
    """

    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None):
        super().__init__(status_code=status_code, detail={"code": code, "message": message}, headers=headers)


def not_found(message: str = "Resource not found.", code: str = "NOT_FOUND") -> ApiError:
    return ApiError(404, code, message)


def forbidden(message: str = "You do not have access to this resource.", code: str = "FORBIDDEN") -> ApiError:
    return ApiError(403, code, message)


def unauthorized(message: str = "Authentication required.", code: str = "UNAUTHORIZED") -> ApiError:
    return ApiError(401, code, message)


def bad_request(message: str, code: str = "BAD_REQUEST") -> ApiError:
    return ApiError(400, code, message)
