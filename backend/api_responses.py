from rest_framework.response import Response


def success_response(message, data=None, status_code=200):
    return Response(
        {
            "success": True,
            "message": message,
            "data": data if data is not None else {},
            "errors": [],
        },
        status=status_code,
    )


def error_response(message, status_code=400, errors=None):
    normalized_errors = errors if errors is not None else [{"detail": message}]
    return Response(
        {
            "success": False,
            "message": message,
            "data": None,
            "errors": normalized_errors,
        },
        status=status_code,
    )

