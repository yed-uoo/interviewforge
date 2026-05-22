from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from .forms import SignupForm


def signup_view(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('profile')

    else:
        form = SignupForm()

    return render(
        request,
        'accounts/signup.html',
        {'form': form}
    )


@login_required
def profile_view(request):
    return render(request, 'accounts/profile.html')


def logout_view(request):
    logout(request)
    return redirect('login')