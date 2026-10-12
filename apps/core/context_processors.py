from .models import Company


def company(request):
    if not request.user.is_authenticated:
        return {}
    return {"company": Company.load()}
