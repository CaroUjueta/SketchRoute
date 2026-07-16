import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.projects.models import Project
from .models import Plan
from .views import is_stale


class IsStaleTests(TestCase):
    def test_sin_last_saved_no_es_conflicto(self):
        self.assertFalse(is_stale(None, timezone.now()))
        self.assertFalse(is_stale('', timezone.now()))

    def test_mismo_instante_no_es_conflicto(self):
        now = timezone.now()
        self.assertFalse(is_stale(now.isoformat(), now))

    def test_timestamp_distinto_es_conflicto(self):
        now = timezone.now()
        self.assertTrue(is_stale((now - timedelta(seconds=5)).isoformat(), now))

    def test_formato_irreconocible_es_conflicto(self):
        self.assertTrue(is_stale('no-es-fecha', timezone.now()))


class SaveCanvasTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa', password='x')
        self.project = Project.objects.create(user=self.user, name='P', description='')
        self.plan = Plan.objects.create(project=self.project, name='plano')
        self.client.force_login(self.user)
        self.url = reverse('plan_save', args=[self.plan.pk])

    def post(self, **body):
        return self.client.post(self.url, json.dumps(body), content_type='application/json')

    def test_guarda_y_devuelve_updated_at(self):
        r = self.post(canvas_data={'objects': []}, last_saved=self.plan.updated_at.isoformat())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertIn('updated_at', r.json())

    def test_conflicto_real_da_409(self):
        stale = (self.plan.updated_at - timedelta(minutes=1)).isoformat()
        r = self.post(canvas_data={'objects': []}, last_saved=stale)
        self.assertEqual(r.status_code, 409)

    def test_canvas_data_invalido_da_400(self):
        r = self.post(canvas_data='no-dict')
        self.assertEqual(r.status_code, 400)
