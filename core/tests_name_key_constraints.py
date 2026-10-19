"""Database-level regression: preserve expanded Unicode keys and reject duplicates."""
import unicodedata
from uuid import uuid4
from django.apps import apps
from django.db import connection, IntegrityError, transaction
from django.test import TestCase


class NameKeyConstraintTests(TestCase):
    def test_full_unicode_keys_remain_unique_in_the_database(self):
        from entities.models import Entity
        entity = Entity.objects.create(name='مرجع اختبار المفاتيح ' + uuid4().hex[:8], entity_type='government')
        targets = {
            'entities.Entity': {'entity_type': 'government'},
            'expense_items.ExpenseItem': {}, 'levels.Level': {},
            'partnerships.Partnership': {'entity': entity, 'scope': 'local', 'representative': 'ممثل', 'phone': '+966501234567', 'email': 'keys@example.com'},
            'regions.Region': {}, 'sectors.Sector': {},
            'service_providers.ServiceProvider': {'provider_type': 'government', 'scope': 'local'},
            'specializations.Specialization': {}, 'sponsorship_shapes.SponsorshipShape': {},
            'training_programs.TrainingProgram': {'category': 'qualifying_program', 'is_training': True, 'is_operational': False},
        }
        for label, extra in targets.items():
            with self.subTest(model=label):
                model = apps.get_model(label)
                # This valid character expands to three code points on casefold.
                name = '\u0390' * model._meta.get_field('name').max_length
                key = unicodedata.normalize('NFKC', name).casefold()
                self.assertGreater(len(key), 255)
                self.assertLessEqual(len(key), model._meta.get_field('name_key').max_length)
                first, second = model.objects.bulk_create([
                    model(name=name, name_key=key, **extra),
                    model(name='اختبار آخر ' + uuid4().hex[:8], name_key='other-' + uuid4().hex, **extra),
                ])
                first = model.objects.get(name_key=key)
                second = model.objects.get(name_key=second.name_key)
                self.assertEqual(first.name, name)
                self.assertEqual(first.name_key, key)
                with connection.cursor() as cursor:
                    constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
                self.assertTrue(any(item['unique'] and item['columns'] == ['name_key'] for item in constraints.values()))
                # QuerySet.update bypasses form/model validation: only the DB can protect this.
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.filter(pk=second.pk).update(name_key=key)
