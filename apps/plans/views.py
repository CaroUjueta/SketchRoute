from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Plan


@login_required
def editor_view(request, pk):
    plan = get_object_or_404(Plan, pk=pk, project__user=request.user)
    return render(request, 'plans/editor.html', {'plan': plan})
