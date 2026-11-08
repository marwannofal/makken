"""An upgrade adds scope without changing data, existing grants or states."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RegionalMigrationTests(TransactionTestCase):
    def test_existing_users_remain_unrestricted_and_no_regions_are_invented(self):
        executor=MigrationExecutor(connection)
        latest=executor.loader.graph.leaf_nodes()
        old=[('access_control','0004_execution_modules'),('partnerships','0006_named_name_key_unique')]
        try:
            executor.migrate(old)
            apps=executor.loader.project_state(old).apps
            User=apps.get_model('auth','User');Access=apps.get_model('access_control','UserAccess')
            Entity=apps.get_model('entities','Entity');Partner=apps.get_model('partnerships','Partnership')
            Module=apps.get_model('access_control','Module');Override=apps.get_model('access_control','PermissionOverride')
            user=User.objects.create(username='pre-region-user',email='old@example.com')
            access=Access.objects.create(user=user,page_scope='selected')
            module,_=Module.objects.get_or_create(pk='partnerships',defaults={'title':'الشراكات','route_name':'partnerships:index','operations':['view']})
            access.allowed_pages.add(module)
            grant=Override.objects.create(user=user,module_id='partnerships',operation='view',effect='grant')
            entity=Entity.objects.create(name='جهة الترحيل',name_key='جهة الترحيل',entity_type='government',branch='')
            apps.get_model('care_states','StateColor').objects.get_or_create(state='willingness',defaults={'color':'#24b3af'})
            partner=Partner.objects.create(name='OLD_ORG',name_key='old_org',representative='ممثل',phone='0501234567',email='old@example.com',entity=entity,scope='local',development_state_id='willingness')
            old_time=partner.development_state_at
            executor=MigrationExecutor(connection);executor.migrate(latest)
            apps=executor.loader.project_state(latest).apps
            Access=apps.get_model('access_control','UserAccess');Partner=apps.get_model('partnerships','Partnership')
            upgraded=Access.objects.get(pk=access.pk)
            self.assertEqual(upgraded.region_scope,'all');self.assertFalse(upgraded.allowed_regions.exists())
            self.assertEqual(list(upgraded.allowed_pages.values_list('pk',flat=True)),['partnerships'])
            self.assertTrue(apps.get_model('access_control','PermissionOverride').objects.filter(pk=grant.pk,effect='grant').exists())
            upgraded_partner=Partner.objects.get(pk=partner.pk)
            self.assertEqual(upgraded_partner.development_state_id,'willingness');self.assertEqual(upgraded_partner.development_state_at,old_time)
            self.assertFalse(upgraded_partner.administrative_regions.exists())
        finally:
            MigrationExecutor(connection).migrate(latest)
