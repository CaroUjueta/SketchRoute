from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from apps.plans.models import Plan


@login_required
def export_options(request, plan_pk):
    plan = get_object_or_404(Plan, pk=plan_pk, user=request.user)
    return render(request, 'export/export_options.html', {'plan': plan})
