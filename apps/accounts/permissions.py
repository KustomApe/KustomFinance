from functools import wraps

from django.core.exceptions import PermissionDenied


def require_capability(capability: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.can(capability):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


class RoleRequiredMixin:
    required_capability: str = ""

    def dispatch(self, request, *args, **kwargs):
        if self.required_capability and not request.user.can(self.required_capability):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
