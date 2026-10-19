from django.core.management.base import BaseCommand
from access_control.defaults import initialize


class Command(BaseCommand):
    help='Initialize registered module permissions and Watcher/Editor without changing existing grants.'
    def handle(self,*args,**options):
        initialize();self.stdout.write(self.style.SUCCESS('تمت تهيئة الأدوار والصفحات. لم تُمنح أي صلاحيات تلقائيًا للمستخدمين الحاليين.'))
