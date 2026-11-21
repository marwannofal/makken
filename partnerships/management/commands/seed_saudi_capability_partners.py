"""Idempotent management command to seed the 64 Saudi capability (قدرة) partner organizations."""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from care_states.models import DevelopmentState, StateColor
from entities.models import Entity, EntityBranch, EntityType, normalize_name
from partnerships.models import DevelopmentHistory, Partnership, Scope

SAUDI_CAPABILITY_PARTNERS = [
    ('وزارة المالية', 'government', '19990', 'ccc@mof.gov.sa', '1000000'),
    ('وزارة الصحة', 'government', '937', '937@moh.gov.sa', '1000000'),
    ('وزارة الاستثمار', 'government', '8002449990', 'InvestorCare@misa.gov.sa', '80000000000'),
    ('وزارة النقل والخدمات اللوجستية', 'government', '+966118744444', 'info@mot.gov.sa', '1000000'),
    ('وزارة الثقافة', 'government', '8001189999', 'info@moc.gov.sa', '80000000000'),
    ('وزارة الاقتصاد والتخطيط', 'government', '+966114011444', 'info@mep.gov.sa', '2000000'),
    ('وزارة التجارة', 'government', '+966920000667', 'cs@mc.gov.sa', '1000000'),
    ('وزارة الحج والعمرة', 'government', '+966920002814', 'hajcc@haj.gov.sa', '80000000000'),
    ('وزارة الخارجية', 'government', '+966114055000', 'info@mofa.gov.sa', '1000000'),
    ('وزارة البيئة والمياه والزراعة', 'government', '+966114016666', 'moait@moa.gov.sa', '1000000'),
    ('الهيئة العامة للإحصاء', 'government', '+966114059493', 'info@stats.gov.sa', '2000000'),
    ('الهيئة العامة للطيران المدني', 'government', '+966112682763', 'gaca-info@gaca.gov.sa', '1000000'),
    ('الهيئة العامة للأوقاف', 'government', '+966920000136', 'info@awqaf.gov.sa', '780000000'),
    ('صندوق التنمية الصناعية السعودي', 'private_large', '8001160004', '', '2000000'),
    ('الشركة السعودية للصناعات الأساسية (سابك)', 'private_large', '+966112258000', 'IR@SABIC.com', '1000000'),
    ('شركة الاتصالات السعودية (stc)', 'private_large', '8001161100', 'IRU@stc.com.sa', '80000000000'),
    ('شركة التعدين العربية السعودية (معادن)', 'private_large', '+966118748000', 'MarketCompliance@maaden.com.sa', '80000000000'),
    ('مصرف الراجحي', 'private_large', '', 'shareholders@alrajhibank.com.sa', '1000000'),
    ('بنك الرياض', 'private_large', '', 'Investor.relations@riyadbank.com', '850000000'),
    ('الشركة السعودية للكهرباء', 'private_large', '920001100', 'SEC-SH@se.com.sa', '80000000000'),
    ('شركة المراعي', 'private_large', '', '', '2000000'),
    ('الشركة السعودية للتأمين التعاوني (سايكو)', 'private_large', '', 'investor.relations@saico.com.sa', '1000000'),
    ('شركة أسمنت السعودية', 'private_large', '', 'saudicement@saudicement.com.sa', '80000000000'),
    ('الشركة السعودية للخدمات الأرضية', 'private_large', '', 'mdhaifallah@saudiags.com', '1000000'),
    ('شركة لُبريف (أرامكو السعودية لزيوت الأساس)', 'private_large', '', 'IR@luberef.com', '1000000'),
    ('شركة ساكو', 'private_large', '', 'investors@saco-ksa.com', '80000000000'),
    ('الشركة السعودية للكابلات', 'private_large', '', 'Investor.Relations@saudicable.com', '1000000'),
    ('الشركة السعودية للخدمات الصناعية (سيسكو)', 'private_large', '', '', '80000000000'),
    ('شركة أكوا باور', 'private_large', '+966112835555', 'ir@acwapower.com', '2000000'),
    ('شركة أرامكو السعودية', 'private_large', '+966138720115', 'investor.relations@aramco.com', '1000000'),
    ('مجموعة الدكتور سليمان الحبيب الطبية', 'private_large', '+966115259999', 'investor.relations@drsulaimanalhabib.com', '80000000000'),
    ('شركة دله الصحية', 'private_large', '', '', '1000000'),
    ('شركة الحمادي القابضة', 'private_large', '+966112329999', 'invest@alhammadi.com', '1000000'),
    ('شركة فقيه الطبية', 'private_large', '+966126655000', 'investors@fakeeh.care', '2000000'),
    ('شركة ناس للطيران (طيران ناس)', 'private_large', '+966114078602', 'ir@flynas.com', '80000000000'),
    ('شركة مرافق الكهرباء والمياه بالجبيل وينبع (مرافق)', 'private_large', '+966133429469', 'InvestorRelations@marafiq.com.sa', '1000000'),
    ('شركة الدواء للخدمات الطبية', 'private_large', '+966920000838', 'investor.relations@al-dawaa.com.sa', '1000000'),
    ('شركة دراية المالية', 'private_large', '+966112998000', 'support@derayah.com', '780000000'),
    ('شركة الرياض للكابلات', 'private_large', '+966112650850', 'IR@riyadh-cables.com', '2000000'),
    ('الشركة العربية للحفر', 'private_large', '+966138297302', 'ir@arabdrill.com', '1000000'),
    ('شركة أسمنت الرياض', 'private_large', '+966112611888', 'IR@riyadhcement.com.sa', '80000000000'),
    ('شركة لازوردي للمجوهرات', 'private_large', '+966112651119', 'investors@lazurde.com', '80000000000'),
    ('شركة لجام للرياضة', 'private_large', '+966112101015', 'investor.relations@leejam.com.sa', '1000000'),
    ('شركة ريدان الغذائية', 'private_large', '+966126781177', 'corporate.governance@raydan.com.sa', '850000000'),
    ('مجموعة باعظيم التجارية', 'private_large', '+966114129999', 'bodirectores@baazeem.com', '80000000000'),
    ('شركة بحر العرب لأنظمة المعلومات', 'private_large', '+966114964444', 'IR@arabsea.com', '1000000'),
    ('شركة العُمران للصناعة والتجارة', 'private_large', '+966112305566', 'info@alomranco.com', '355550000'),
    ('شركة عبدالله سعد أبو معطي للمكتبات', 'private_large', '+966114010113', 'investorrelations@abomoati.com', '80000000000'),
    ('مجموعة تداول السعودية القابضة', 'private_large', '+966920013130', 'I.R@tadawulgroup.sa', '1000000'),
    ('الشركة السعودية للنقل الجماعي (سابتكو)', 'private_large', '', 'IR@saptco.com.sa', '1000000'),
    ('شركة الصادرات الصناعية', 'private_large', '', '', '2000000'),
    ('شركة بوبا العربية للتأمين التعاوني', 'private_large', '', 'invest@bupa.com.sa', '80000000000'),
    ('مصرف الإنماء', 'private_large', '', 'shareholders@Alinma.com', '1000000'),
    ('بنك البلاد', 'private_large', '', 'IR@bankalbilad.com', '1000000'),
    ('بنك الجزيرة', 'private_large', '', 'ialjedda@baj.com.sa', '780000000'),
    ('شركة أسواق عبدالله العثيم', 'private_large', '', 'ir@othaimmarkets.com', '2000000'),
    ('شركة بن داود القابضة', 'private_large', '', 'investors@bindawood.com', '1000000'),
    ('مجموعة سافولا', 'private_large', '', 'CGNour@savola.com', '80000000000'),
    ('الشركة السعودية للصناعات الدوائية والمستلزمات الطبية (سبيماكو)', 'private_large', '', 'investor.relations@spimaco.sa', '80000000000'),
    ('الشركة السعودية لإعادة التأمين (إعادة)', 'private_large', '', 'Invest@saudi-re.com', '1000000'),
    ('مجموعة السعودية للأبحاث والإعلام', 'private_large', '', 'Investors.relations@srmg.com', '850000000'),
    ('شركة كاتريون للتموين القابضة', 'private_large', '', 'mazouz@catrion.com', '80000000000'),
    ('شركة سينومي ريتيل', 'private_large', '', 'IR@alhokair.com', '1000000'),
    ('شركة العربية للتعهدات الفنية', 'private_large', '', 'IR@al-arabia.com', '355550000'),
]


class Command(BaseCommand):
    help = "Seed the 64 Saudi government and large private organizations into شراكات القدرة (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        StateColor.objects.get_or_create(state=DevelopmentState.CAPABILITY, defaults={'color': '#BA1D1D'})
        gov_entity = Entity.objects.filter(entity_type=EntityType.GOVERNMENT, is_active=True).order_by('id').first()
        if gov_entity is None:
            gov_entity = Entity.objects.create(name='حكومي', entity_type=EntityType.GOVERNMENT, is_active=True)

        large_entity = Entity.objects.filter(
            entity_type=EntityType.NON_GOVERNMENT,
            branch=EntityBranch.PRIVATE_LARGE,
            is_active=True,
        ).order_by('id').first()
        if large_entity is None:
            large_entity = Entity.objects.create(
                name='خاص كبير',
                entity_type=EntityType.NON_GOVERNMENT,
                branch=EntityBranch.PRIVATE_LARGE,
                is_active=True,
            )

        created_count = 0
        skipped_count = 0
        for name, kind, phone, email, cap_str in SAUDI_CAPABILITY_PARTNERS:
            clean_name = normalize_name(name)
            key = clean_name.casefold()
            if Partnership.objects.filter(name_key=key).exists():
                skipped_count += 1
                continue
            entity = gov_entity if kind == 'government' else large_entity
            partnership = Partnership.objects.create(
                name=clean_name,
                representative='غير محدد',
                phone_country='SA',
                phone=phone,
                email=email,
                financial_capacity=Decimal(cap_str) if cap_str else None,
                entity=entity,
                scope=Scope.LOCAL,
                is_active=True,
                development_state_id=DevelopmentState.CAPABILITY,
            )
            DevelopmentHistory.objects.get_or_create(
                partnership=partnership,
                state_id=DevelopmentState.CAPABILITY,
            )
            created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Seeded capability partners: created={created_count}, skipped_existing={skipped_count}, total_in_list={len(SAUDI_CAPABILITY_PARTNERS)}'
            )
        )
