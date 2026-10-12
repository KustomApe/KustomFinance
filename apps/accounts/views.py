from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from . import roles
from .forms import LoginForm, StyledPasswordChangeForm, UserCreateForm, UserEditForm
from .models import User
from .permissions import require_capability


class LoginView(auth_views.LoginView):
    authentication_form = LoginForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True


class PasswordChangeView(auth_views.PasswordChangeView):
    form_class = StyledPasswordChangeForm
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("core:dashboard")

    def form_valid(self, form):
        messages.success(self.request, "パスワードを変更しました。")
        return super().form_valid(form)


@require_capability(roles.SETTINGS)
def user_list(request):
    return render(request, "accounts/user_list.html", {"users": User.objects.order_by("username")})


@require_capability(roles.SETTINGS)
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "ユーザーを作成しました。")
        return redirect("accounts:users")
    return render(request, "accounts/user_form.html", {"form": form})


@require_capability(roles.SETTINGS)
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = UserEditForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        if user == request.user and not form.cleaned_data["is_active"]:
            form.add_error("is_active", "自分自身を無効にすることはできません。")
        else:
            form.save()
            messages.success(request, "ユーザーを更新しました。")
            return redirect("accounts:users")
    return render(request, "accounts/user_form.html", {"form": form, "object": user})
