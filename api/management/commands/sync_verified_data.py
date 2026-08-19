from datetime import date

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.models import CalendarEvent, Concours


SOURCE_NAME = "MINFOPRA — arrêté officiel ENAM 2026"
ENAM_PDF_BASE = "https://www.minfopra.gov.cm/images/2026/DDRHE/CONCOURS/ENAM/"


class Command(BaseCommand):
    help = "Supprime les données de démonstration connues et synchronise uniquement des concours vérifiés."

    @transaction.atomic
    def handle(self, *args, **options):
        demo_emails = [
            'admin@prepconcours.cm', 'enseignant@prepconcours.cm', 'candidat@prepconcours.cm',
            'admin@test.cm', 'candidat_nouveau@test.cm', 'marie.nguema@test.cm', 'felix.mbarga@test.cm',
        ]
        deleted_users, _ = User.objects.filter(email__in=demo_emails).delete()

        Concours.objects.filter(id_code__in=[
            'enam-a', 'iai-ingenierie', 'fmsb-medecine', 'ens-enseignement', 'police-emia',
        ]).delete()
        Concours.objects.filter(source_url='').delete()

        verified_at = timezone.now()
        records = [
            ('enam-2026-admin-a', 'ENAM 2026 — Cycle A, Division administrative', date(2026, 9, 12), '70_Elves_Div_Administrative_A_Fr.pdf'),
            ('enam-2026-finances-a', 'ENAM 2026 — Cycle A, Division des régies financières', date(2026, 9, 19), '20_Elves_Div_RF_A_Fr.pdf'),
            ('enam-2026-justice', 'ENAM 2026 — Auditeurs de justice', date(2026, 8, 1), '40_Auditeurs_de_Justice_DMG_Fr.pdf'),
            ('enam-2026-greffes-a', 'ENAM 2026 — Greffes, Cycle A', date(2026, 8, 22), '10_Admin_Greffes_A_Fr.pdf'),
            ('enam-2026-admin-b', 'ENAM 2026 — Cycle B, Division administrative', date(2026, 9, 5), '50_Elves_Div_Administrative_B_Fr.pdf'),
            ('enam-2026-finances-b', 'ENAM 2026 — Cycle B, Division des régies financières', date(2026, 8, 29), '20_Elves_Div_RF_B_Fr.pdf'),
            ('enam-2026-greffes-b', 'ENAM 2026 — Greffes, Cycle B', date(2026, 8, 8), '10_Elves_Greffiers_B_Fr.pdf'),
        ]

        for code, title, exam_date, source_file in records:
            existing = Concours.objects.filter(id_code=code).first()
            concours, _ = Concours.objects.update_or_create(
                id_code=code,
                defaults={
                    'title': title,
                    'category': 'Administratif et juridique',
                    'session': '2026',
                    'modules': existing.modules if existing else [],
                    'subjects': existing.subjects if existing else [],
                    'requirements': existing.requirements if existing else [],
                    'career_paths': existing.career_paths if existing else [],
                    'description': "Concours d'entrée à l'École Nationale d'Administration et de Magistrature, session 2026.",
                    'exam_date': exam_date,
                    'registration_deadline': date(2026, 8, 14),
                    'source_name': SOURCE_NAME,
                    'source_url': ENAM_PDF_BASE + source_file,
                    'verified_at': verified_at,
                    'active': True,
                    'candidates_count': 0,
                },
            )
            CalendarEvent.objects.update_or_create(
                user=None,
                title=f"Épreuves — {title}",
                event_date=exam_date,
                defaults={
                    'concourse_name': title,
                    'event_type': 'ecrit',
                    'description': f"Date publiée par {SOURCE_NAME}. Vérifiez la source officielle avant déplacement.",
                },
            )

        CalendarEvent.objects.update_or_create(
            user=None,
            title='Date limite de dépôt des dossiers ENAM 2026',
            event_date=date(2026, 8, 14),
            defaults={
                'concourse_name': 'ENAM 2026',
                'event_type': 'deadline',
                'description': f"Date publiée par {SOURCE_NAME}.",
            },
        )

        self.stdout.write(self.style.SUCCESS(
            f"Synchronisation terminée : {len(records)} concours officiels, {deleted_users} objets utilisateurs de démonstration supprimés."
        ))
