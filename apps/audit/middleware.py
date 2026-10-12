from .context import current_ip, current_user


class AuditContextMiddleware:
    """操作ログに記録するため、リクエスト中のユーザーとIPを保持する。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user if request.user.is_authenticated else None
        user_token = current_user.set(user)
        ip_token = current_ip.set(request.META.get("REMOTE_ADDR"))
        try:
            return self.get_response(request)
        finally:
            current_user.reset(user_token)
            current_ip.reset(ip_token)
