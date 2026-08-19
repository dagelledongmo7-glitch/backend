from datetime import date, timedelta
import os
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from api.models import (
    Activity, CalendarEvent, Concours, Enrollment, ForumReply, ForumTopic,
    LearningContent, Notification, Resource, Subscription, TutorAppointment,
    TutorMessage, UserProfile,
)


MINFOPRA_2026 = 'https://www.minfopra.gov.cm/index.php/fr/publications/2363-concours-administratifs-la-saison-2026-est-ouverte'
ENAM = 'https://concours.enam.cm/fr/accueil.aspx'
ENS = 'https://concours.ens.cm/inscription/'
MINESUP_ENS = 'https://www.minesup.gov.cm/index.php/2026/01/13/concours-dentree-dans-les-ens-et-enset-au-titre-de-lannee-academique-2025-2026/'
MINESUP_SCHOOLS = 'https://www.minesup.gov.cm/index.php/2026/06/02/decisions-portant-ouverture-des-concours-dans-cesrtaines-grandes-ecoles-des-universites-detat/'
IAI_CAMEROUN_2026 = 'https://www.iaicameroun.com/concours'
IAI_CAMEROUN_ADMISSIONS = 'https://www.unescochaire-tic.org/preinscription-2026'
ENAM_ADMIN_A_PDF = 'https://www.minfopra.gov.cm/images/2025/DDRHE/SAISON2025/ENAM/60_Eleves_Div_Administrative_A_Fr.pdf'
ENAM_ADMIN_B_PDF = 'https://www.minfopra.gov.cm/images/2025/DDRHE/SAISON2025/ENAM/60_Eleves_Div_Administrative_B_Fr.pdf'
ENAM_FINANCE_PDF = 'https://www.minfopra.gov.cm/images/2025/DDRHE/SAISON2025/ENAM/20_Eleves_Div_RF_A_Fr.pdf'
ENAM_JUSTICE_PDF = 'https://www.minfopra.gov.cm/images/2025/DDRHE/SAISON2025/ENAM/40_Auditeurs_de_Justice_DMG_Fr.pdf'
LESSON_VIDEOS = {
    'Introduction structurée': 'https://www.youtube.com/watch?v=70HwSfHFyqU',
    'Objectifs pédagogiques': 'https://www.youtube.com/watch?v=VpkR0d7oaAY',
    'Lecture active de l’actualité': 'https://www.youtube.com/watch?v=GwCpdjh6tog',
}

AFRICAN_EDUCATION_VIDEOS = {
    'pédagog': 'https://www.youtube.com/watch?v=VpkR0d7oaAY',
    'enseignement': 'https://www.youtube.com/watch?v=w6z9n5AlFSY',
    'culture': 'https://www.youtube.com/watch?v=70HwSfHFyqU',
    'économie': 'https://www.youtube.com/watch?v=hpeYJdVuGHg',
    'informatique': 'https://www.youtube.com/watch?v=hpeYJdVuGHg',
    'math': 'https://www.youtube.com/watch?v=ZLbSZs4or3Q',
}


class Command(BaseCommand):
    help = 'Peuple la plateforme avec un catalogue sourcé et des contenus pédagogiques identifiés.'

    @transaction.atomic
    def handle(self, *args, **options):
        self.seed_password = os.getenv('POPULATE_DEFAULT_PASSWORD', '')
        if not self.seed_password:
            raise CommandError('Définissez POPULATE_DEFAULT_PASSWORD avant de créer les comptes de peuplement.')
        call_command('sync_verified_data', verbosity=0)
        now = timezone.now()
        teachers = [
            self.upsert_user('prof1@gmail.com', 'Professeur', 'Droit public', 'enseignant'),
            self.upsert_user('prof2@gmail.com', 'Professeur', 'Pédagogie', 'enseignant'),
            self.upsert_user('prof3@gmail.com', 'Professeur', 'Méthodologie', 'enseignant'),
        ]
        teacher_details = [
            ('Droit public et méthodologie juridique', 'Enseignant référent pour les compositions juridiques, les cas pratiques et la préparation aux concours administratifs.'),
            ('Pédagogie et sciences de l’éducation', 'Enseignant référent pour les concours de l’enseignement, la didactique et la préparation des oraux.'),
            ('Méthodologie générale et culture générale', 'Enseignant référent pour la structuration des dissertations, la culture générale et les stratégies de révision.'),
        ]
        for teacher, (specialty, bio) in zip(teachers, teacher_details):
            teacher.profile.specialty = specialty
            teacher.profile.bio = bio
            teacher.profile.university = 'Équipe pédagogique Prep Concours'
            teacher.profile.save(update_fields=['specialty', 'bio', 'university'])
        tekeng = self.upsert_user('tekeng@gmail.com', 'Tekeng', '', 'candidat')
        tekeng.profile.target_concours = 'ENAM 2026 — Cycle A, Division administrative'
        tekeng.profile.diploma = 'Non renseigné'
        tekeng.profile.save(update_fields=['target_concours', 'diploma'])

        concours_specs = [
            ('injs-2026-peps', 'INJS 2026 — PEPS et PAEPS', 'Jeunesse et sports', '2026', MINFOPRA_2026,
             ['Culture générale', 'Éducation physique et sportive'], ['Carrières de l’éducation physique et sportive']),
            ('injs-2026-cpja', 'INJS 2026 — CPJA et CJA', 'Jeunesse et animation', '2026', MINFOPRA_2026,
             ['Culture générale', 'Jeunesse et animation'], ['Encadrement de la jeunesse et animation']),
            ('ens-yde-2026-cycle1', 'ENS Yaoundé I 2026 — 1er cycle', 'Enseignement', '2025-2026', ENS,
             ['Culture générale', 'Matière de spécialité'], ['Enseignement secondaire général']),
            ('ens-yde-2026-cycle2', 'ENS Yaoundé I 2026 — 2nd cycle', 'Enseignement', '2025-2026', ENS,
             ['Sciences de l’éducation', 'Matière de spécialité'], ['Enseignement secondaire général']),
            ('enset-douala-2026', 'ENSET Douala 2026 — 1er et 2nd cycles', 'Enseignement technique', '2025-2026', MINESUP_ENS,
             ['Culture générale', 'Matières techniques de spécialité'], ['Enseignement technique']),
            ('enstp-yde-2026', 'ENSTP Yaoundé 2026-2027 — Cycle ingénieur', 'Ingénierie', '2026-2027', 'https://www.minesup.gov.cm/index.php/2026/06/02/',
             ['Mathématiques', 'Physique', 'Culture générale'], ['Génie civil', 'Génie environnement', 'Topographie-cadastre', 'Génie rural']),
            ('essec-garoua-2026', 'ESSEC Garoua 2026-2027', 'Commerce et gestion', '2026-2027', MINESUP_SCHOOLS,
             ['Culture générale', 'Économie', 'Mathématiques'], ['Gestion', 'Commerce', 'Management']),
            ('iut-ngaoundere-2026', 'IUT de Ngaoundéré 2026-2027', 'Technologie', '2026-2027', MINESUP_SCHOOLS,
             ['Mathématiques', 'Physique', 'Informatique'], ['Technologies industrielles et numériques']),
            ('iai-cameroun-2026-travaux', 'IAI-Cameroun 2026-2027 — Élèves ingénieurs des travaux informatiques', 'Informatique et numérique', '2026-2027', IAI_CAMEROUN_2026,
             ['Mathématiques et logique', 'Algorithmique et programmation', 'Génie logiciel', 'Systèmes et réseaux', 'Anglais technique'],
             ['Développement logiciel', 'Administration systèmes et réseaux', 'Analyse-programmation', 'Cybersécurité', 'Ingénierie informatique']),
        ]
        for code, title, category, session, source_url, subjects, careers in concours_specs:
            Concours.objects.update_or_create(
                id_code=code,
                defaults={
                    'title': title, 'category': category, 'session': session,
                    'modules': subjects, 'subjects': subjects, 'requirements': [],
                    'career_paths': careers,
                    'description': 'Fiche de concours ouverte à partir de la publication de l’organisme compétent. Consultez la source pour les conditions détaillées.',
                    'source_name': 'MINFOPRA' if 'minfopra' in source_url else ('ENS Yaoundé I' if 'concours.ens.cm' in source_url else 'MINESUP'),
                    'source_url': source_url, 'verified_at': now, 'active': True,
                    'registration_deadline': date(2026, 2, 13) if code.startswith('ens-yde') else None,
                },
            )

        iai = Concours.objects.get(id_code='iai-cameroun-2026-travaux')
        iai.requirements = [
            'Génie logiciel : baccalauréat ou GCE A-Level, toutes séries, selon la publication 2026.',
            'Systèmes et réseaux : baccalauréat scientifique ou technique, selon la publication 2026.',
            'Déposer le dossier complet au plus tard le 28 juillet 2026 à 12 h et vérifier toute mise à jour sur la page officielle.',
        ]
        iai.description = (
            'Concours d’entrée en première année de l’IAI-Cameroun, Centre d’Excellence Technologique Paul BIYA, '
            'pour les options Génie logiciel et Systèmes et réseaux. Les dates et conditions enregistrées proviennent '
            'de la publication 2026 ; les examens de préparation de la plateforme sont explicitement pédagogiques.'
        )
        iai.source_name = 'IAI-Cameroun — publication concours 2026-2027'
        iai.source_url = IAI_CAMEROUN_2026
        iai.registration_deadline = date(2026, 7, 28)
        iai.exam_date = date(2026, 7, 31)
        iai.save(update_fields=['requirements', 'description', 'source_name', 'source_url', 'registration_deadline', 'exam_date'])
        CalendarEvent.objects.update_or_create(
            user=None, title='Concours IAI-Cameroun 2026 — session de juillet', event_date=date(2026, 7, 31),
            defaults={'concourse_name': iai.title, 'event_type': 'ecrit', 'event_time': '07:30',
                      'description': 'Date publiée pour la session de juillet 2026. Vérifier toute nouvelle session sur le site IAI-Cameroun.'},
        )
        CalendarEvent.objects.update_or_create(
            user=None, title='Clôture des dossiers IAI-Cameroun — session de juillet', event_date=date(2026, 7, 28),
            defaults={'concourse_name': iai.title, 'event_type': 'deadline', 'event_time': '12:00',
                      'description': 'Échéance enregistrée depuis la publication du concours 2026.'},
        )

        admin_a = Concours.objects.get(id_code='enam-2026-admin-a')
        ens_cycle1 = Concours.objects.get(id_code='ens-yde-2026-cycle1')
        admin_a.modules = ['Culture générale', 'Droit public', 'Économie', 'Institutions administratives']
        admin_a.subjects = admin_a.modules
        admin_a.requirements = ['Vérifier le diplôme, l’âge et les pièces dans l’arrêté officiel avant inscription.']
        admin_a.career_paths = ['Administration générale', 'Administration du travail', 'Affaires sociales']
        admin_a.save(update_fields=['modules', 'subjects', 'requirements', 'career_paths'])

        Enrollment.objects.get_or_create(user=tekeng, concourse=admin_a)
        Enrollment.objects.get_or_create(user=tekeng, concourse=ens_cycle1)

        course_specs = [
            ('course-enam-droit-public', admin_a, teachers[0], 'Fondamentaux du droit public', 'Droit public', [
                ('Sources et hiérarchie des normes', ['Constitution et normes supérieures', 'Loi et règlement', 'Contrôle de légalité']),
                ('Organisation administrative', ['Administration centrale', 'Collectivités territoriales', 'Services publics']),
                ('Acte administratif', ['Décision administrative', 'Entrée en vigueur', 'Recours et retrait']),
            ], ENAM_ADMIN_A_PDF),
            ('course-enam-culture-generale', admin_a, teachers[2], 'Méthodologie de culture générale', 'Culture générale', [
                ('Analyser un sujet', ['Définir les termes', 'Délimiter le sujet', 'Construire une problématique']),
                ('Construire la copie', ['Introduction structurée', 'Plan argumenté', 'Transitions et conclusion']),
                ('S’entraîner', ['Lecture active de l’actualité', 'Fiche thématique', 'Composition chronométrée']),
            ], ENAM_ADMIN_A_PDF),
            ('course-enam-economie', admin_a, teachers[0], 'Économie et finances publiques', 'Économie', [
                ('Notions économiques', ['Croissance et développement', 'Inflation et emploi', 'Politiques économiques']),
                ('Finances publiques', ['Budget de l’État', 'Recettes et dépenses', 'Contrôle budgétaire']),
            ], ENAM_FINANCE_PDF),
            ('course-ens-pedagogie', ens_cycle1, teachers[1], 'Introduction aux sciences de l’éducation', 'Pédagogie', [
                ('Apprentissage', ['Objectifs pédagogiques', 'Évaluation diagnostique', 'Évaluation formative']),
                ('Conduite de classe', ['Préparer une séquence', 'Gérer les interactions', 'Différencier les activités']),
                ('Éthique professionnelle', ['Responsabilité de l’enseignant', 'Inclusion scolaire', 'Communication éducative']),
            ], MINESUP_ENS),
            ('course-ens-expression', ens_cycle1, teachers[2], 'Expression française et raisonnement', 'Français', [
                ('Compréhension', ['Repérer la thèse', 'Identifier les arguments', 'Reformuler fidèlement']),
                ('Expression écrite', ['Construire un paragraphe', 'Maîtriser les connecteurs', 'Relire et corriger']),
            ], ENS),
            ('course-commun-organisation', None, teachers[2], 'Organisation personnelle de la préparation', 'Méthodologie', [
                ('Planifier', ['Faire l’inventaire du programme', 'Construire un calendrier', 'Mesurer sa progression']),
                ('Réviser activement', ['Rappel actif', 'Répétition espacée', 'Analyse des erreurs']),
            ], MINFOPRA_2026),
        ]
        for slug, concours, author, title, subject, modules, source_url in course_specs:
            data_modules = []
            lesson_count = 0
            for module_index, (module_title, lessons) in enumerate(modules, start=1):
                lesson_rows = []
                for lesson_index, lesson_title in enumerate(lessons, start=1):
                    lesson_count += 1
                    video_url = LESSON_VIDEOS.get(lesson_title, '')
                    lesson_rows.append({
                        'id': f'{slug}-m{module_index}-l{lesson_index}', 'title': lesson_title,
                        'type': 'video' if video_url else ('pdf' if lesson_index % 2 == 0 else 'exercise'), 'duration': '18 min',
                        'completed': False,
                        'summary': f'Cette leçon présente « {lesson_title} » dans le cadre du module « {module_title} ». Appuyez-vous sur la source liée et réalisez une fiche personnelle.',
                        'url': video_url or source_url,
                        'videoUrl': video_url,
                        'documentUrl': source_url if (not video_url and source_url.lower().endswith('.pdf')) else '',
                        'content': self.lesson_content(lesson_title, module_title, subject),
                    })
                data_modules.append({'id': f'{slug}-m{module_index}', 'title': module_title, 'lessons': lesson_rows})
            self.upsert_content(slug, 'course', title, concours, author, {
                'subject': subject, 'instructor': author.get_full_name(),
                'description': f'Parcours pédagogique structuré en {len(data_modules)} modules, associé à une source consultable.',
                'level': 'Intermédiaire', 'duration': f'{lesson_count * 18} min',
                'lessonsCount': lesson_count, 'progress': 0, 'modules': data_modules,
            }, 'Programme de concours publié', source_url)

        general_questions = self.enam_questions()
        ens_questions = self.ens_questions()
        self.upsert_quiz('quiz-enam-fondamentaux', admin_a, teachers[0], 'Quiz ENAM — fondamentaux', general_questions, ENAM_ADMIN_A_PDF)
        self.upsert_quiz('quiz-ens-pedagogie', ens_cycle1, teachers[1], 'Quiz ENS — pédagogie et expression', ens_questions, MINESUP_ENS)
        self.upsert_quiz('quiz-enam-entrainement-2', admin_a, teachers[2], 'Quiz ENAM — entraînement complémentaire', list(reversed(general_questions)), ENAM_ADMIN_A_PDF)

        self.upsert_exam('exam-enam-complet', admin_a, teachers[0], 'Examen blanc ENAM — simulation complète', general_questions, ENAM_ADMIN_A_PDF)
        self.upsert_exam('exam-ens-complet', ens_cycle1, teachers[1], 'Examen blanc ENS — simulation complète', ens_questions, MINESUP_ENS)

        flashcards = [
            (admin_a, 'Droit public', 'Hiérarchie des normes', 'Organisation des normes juridiques selon leur autorité relative.'),
            (admin_a, 'Droit public', 'Acte administratif unilatéral', 'Décision prise unilatéralement par une autorité administrative et produisant des effets juridiques.'),
            (admin_a, 'Droit public', 'Service public', 'Activité d’intérêt général assumée ou contrôlée par une personne publique.'),
            (admin_a, 'Droit public', 'Décentralisation', 'Transfert de compétences de l’État vers des collectivités dotées d’une autonomie administrative.'),
            (admin_a, 'Économie', 'Inflation', 'Hausse générale et durable du niveau des prix.'),
            (admin_a, 'Économie', 'Budget public', 'Acte prévoyant et autorisant les recettes et dépenses d’une personne publique.'),
            (admin_a, 'Méthodologie', 'Problématique', 'Question directrice qui organise la démonstration et répond aux enjeux précis du sujet.'),
            (admin_a, 'Méthodologie', 'Transition', 'Passage argumenté qui clôt une partie et justifie la suivante.'),
            (ens_cycle1, 'Pédagogie', 'Évaluation diagnostique', 'Évaluation réalisée avant l’apprentissage pour identifier les acquis et besoins.'),
            (ens_cycle1, 'Pédagogie', 'Évaluation formative', 'Évaluation intégrée à l’apprentissage afin d’ajuster l’enseignement et aider à progresser.'),
            (ens_cycle1, 'Pédagogie', 'Objectif pédagogique', 'Résultat observable attendu chez l’apprenant après une activité.'),
            (ens_cycle1, 'Pédagogie', 'Différenciation pédagogique', 'Adaptation des démarches, supports ou rythmes aux besoins des apprenants.'),
            (ens_cycle1, 'Français', 'Thèse', 'Idée principale défendue par l’auteur d’un texte argumentatif.'),
            (ens_cycle1, 'Français', 'Connecteur logique', 'Mot ou groupe de mots qui explicite la relation entre deux idées.'),
            (None, 'Méthodologie', 'Rappel actif', 'Effort de récupération d’une information sans consulter immédiatement le support.'),
            (None, 'Méthodologie', 'Répétition espacée', 'Révisions distribuées dans le temps à intervalles adaptés.'),
        ]
        for index, (concours, subject, front, back) in enumerate(flashcards, start=1):
            self.upsert_content(f'flashcard-{index:02d}', 'flashcard', front, concours, teachers[index % 3], {
                'subject': subject, 'front': front, 'back': back, 'category': 'Paquet pédagogique', 'mastered': False,
            }, 'Contenu pédagogique de la plateforme', concours.source_url if concours else MINFOPRA_2026)

        checkpoint_specs = [
            (admin_a, 1, 'Découvrir le programme ENAM', [('Lire la fiche officielle', 'reading'), ('Terminer le quiz de diagnostic', 'quiz'), ('Créer cinq flashcards', 'reading')]),
            (admin_a, 2, 'Maîtriser les fondamentaux', [('Terminer le cours de droit public', 'reading'), ('Faire un sujet chronométré', 'paper'), ('Analyser les erreurs du quiz', 'quiz')]),
            (admin_a, 3, 'Se placer en conditions d’examen', [('Passer l’examen blanc complet', 'quiz'), ('Réaliser une simulation orale', 'oral'), ('Réviser les cartes non maîtrisées', 'reading')]),
            (ens_cycle1, 1, 'Découvrir le concours ENS', [('Consulter la procédure officielle', 'reading'), ('Choisir sa spécialité', 'reading'), ('Passer le quiz de départ', 'quiz')]),
            (ens_cycle1, 2, 'Consolider pédagogie et expression', [('Terminer le cours de pédagogie', 'reading'), ('Rédiger un plan argumenté', 'paper'), ('Réviser les flashcards', 'reading')]),
            (ens_cycle1, 3, 'Finaliser la préparation ENS', [('Passer l’examen blanc ENS', 'quiz'), ('Préparer une présentation orale', 'oral'), ('Vérifier son dossier', 'reading')]),
        ]
        for concours, number, title, tasks in checkpoint_specs:
            self.upsert_content(f'checkpoint-{concours.id_code}-{number}', 'checkpoint', title, concours, teachers[number % 3], {
                'number': number, 'description': f'Étape {number} du parcours {concours.title}.',
                'concourse': concours.title, 'status': 'in_progress', 'progressPercent': 0,
                'badgeAwarded': f'Étape {number}',
                'tasks': [{'id': f'{concours.id_code}-cp{number}-t{i}', 'title': task, 'type': task_type, 'completed': False, 'points': 25} for i, (task, task_type) in enumerate(tasks, start=1)],
            }, 'Parcours pédagogique associé au concours', concours.source_url)

        oral_specs = [
            (admin_a, 'oral-enam', ['Présentez votre motivation pour servir dans l’administration publique.', 'Expliquez une réforme administrative qui vous paraît importante.', 'Comment organisez-vous votre travail sous contrainte de temps ?']),
            (ens_cycle1, 'oral-ens', ['Pourquoi souhaitez-vous devenir enseignant ?', 'Comment réagir face à une classe hétérogène ?', 'Présentez une méthode pour vérifier la compréhension des élèves.']),
        ]
        for concours, slug, questions in oral_specs:
            self.upsert_content(slug, 'oral_bank', f'Questions orales — {concours.title}', concours, teachers[1], {
                'questions': [{'id': i, 'number': i, 'total': len(questions), 'text': text, 'category': 'Motivation et méthode', 'timeLimitSeconds': 120} for i, text in enumerate(questions, start=1)],
            }, 'Banque pédagogique de la plateforme', concours.source_url)

        plan_specs = [
            ('plan-gratuit', 'Découverte', '0 FCFA', 0, 'sans limite', ['Catalogue sourcé', 'Cours gratuits publiés', 'Suivi de progression'], False),
            ('plan-essentiel', 'Essentiel', '3 500 FCFA', 3500, 'mois', ['Tous les cours publiés', 'Quiz et flashcards', 'Messagerie enseignants', 'Examens blancs'], True),
            ('plan-intensif', 'Intensif', '7 500 FCFA', 7500, 'mois', ['Fonctions Essentiel', 'Génération documentaire', 'Simulations orales avec fournisseur IA', 'Priorité rendez-vous'], False),
        ]
        plans = []
        for slug, name, price, amount, period, features, recommended in plan_specs:
            plans.append(self.upsert_content(slug, 'subscription_plan', name, None, teachers[2], {
                'name': name, 'price': price, 'priceAmount': amount, 'period': period,
                'description': 'Formule publiée par l’administration de la plateforme.',
                'features': features, 'recommended': recommended, 'badge': 'Populaire' if recommended else '',
            }, 'Tarification interne de la plateforme', ''))

        Subscription.objects.update_or_create(
            user=tekeng, plan=plans[0], defaults={'status': 'active', 'payment_method': 'gratuit'},
        )

        resources = [
            ('Programme ENAM — Division administrative Cycle A', admin_a, 'pdf', ENAM_ADMIN_A_PDF, 'Programme officiel', 'Programme et conditions publiés par le MINFOPRA.'),
            ('Programme ENAM — Division administrative Cycle B', admin_a, 'pdf', ENAM_ADMIN_B_PDF, 'Programme officiel', 'Programme et conditions publiés par le MINFOPRA.'),
            ('Programme ENAM — Régies financières', admin_a, 'pdf', ENAM_FINANCE_PDF, 'Programme officiel', 'Programme des matières des régies financières.'),
            ('Programme ENAM — Auditeurs de justice', admin_a, 'pdf', ENAM_JUSTICE_PDF, 'Programme officiel', 'Programme détaillé des matières juridiques.'),
            ('Procédure officielle ENS Yaoundé 2026', ens_cycle1, 'fiche', ENS, 'Inscription', 'Page officielle d’inscription et date limite.'),
            ('Arrêtés ENS et ENSET 2025-2026', ens_cycle1, 'fiche', MINESUP_ENS, 'Arrêtés', 'Répertoire officiel MINESUP des décisions.'),
            ('Sujet d’entraînement ENAM — droit public', admin_a, 'pdf', ENAM_ADMIN_A_PDF, 'Droit public', 'Sujet pédagogique construit à partir des thèmes du programme.'),
            ('Sujet d’entraînement ENAM — culture générale', admin_a, 'pdf', ENAM_ADMIN_A_PDF, 'Culture générale', 'Sujet pédagogique construit à partir des thèmes du programme.'),
            ('Sujet d’entraînement ENS — sciences de l’éducation', ens_cycle1, 'pdf', MINESUP_ENS, 'Pédagogie', 'Sujet pédagogique pour réviser les notions de base.'),
        ]
        for index, (title, concours, resource_type, url, subject, description) in enumerate(resources, start=1):
            preview = {
                7: 'Sujet pédagogique : Montrez comment le principe de légalité encadre l’action administrative.',
                8: 'Sujet pédagogique : L’innovation technologique transforme-t-elle durablement le service public ?',
                9: 'Sujet pédagogique : Proposez une séquence d’apprentissage incluant une évaluation formative.',
            }.get(index, description)
            correction = {
                7: 'Attendus : définir le principe de légalité, présenter la hiérarchie des normes, expliquer les contrôles et illustrer les limites.',
                8: 'Attendus : définir les termes, analyser opportunités et risques, illustrer par des services publics et proposer une conclusion nuancée.',
                9: 'Attendus : objectifs observables, activité guidée, critères de réussite, rétroaction et remédiation.',
            }.get(index, '')
            Resource.objects.update_or_create(
                title=title,
                defaults={
                    'concourse': concours, 'concourse_name': concours.title, 'type': resource_type,
                    'file_name': url.rsplit('/', 1)[-1] or f'resource-{index}', 'url': url,
                    'metadata': {'subject': subject, 'description': description, 'session': concours.session,
                                 'year': 2026, 'duration': '2 h' if index >= 7 else '', 'durationMinutes': 120 if index >= 7 else 0,
                                 'coefficient': 2 if index >= 7 else 0, 'questionsCount': 1 if index >= 7 else 0,
                                 'contentPreview': preview, 'correctionText': correction, 'tags': ['source', concours.category]},
                    'author': teachers[index % 3], 'status': 'published',
                },
            )

        self.populate_every_concours(teachers)
        self.populate_iai_content(iai, teachers)

        self.populate_forum(tekeng, teachers)
        self.populate_messages(tekeng, teachers)
        CalendarEvent.objects.update_or_create(
            user=tekeng, title='Session personnelle — examen blanc ENAM', event_date=date.today() + timedelta(days=3),
            defaults={'concourse_name': admin_a.title, 'event_type': 'exam', 'event_time': '18:00', 'description': 'Session de préparation créée lors de l’initialisation.', 'completed': False},
        )
        Notification.objects.get_or_create(user=tekeng, title='Parcours prêt', message='Vos deux concours, cours, checkpoints, quiz et examens blancs sont disponibles.', type='system')

        self.stdout.write(self.style.SUCCESS(
            f'Population terminée : {Concours.objects.count()} concours, {LearningContent.objects.count()} contenus, '
            f'{Resource.objects.count()} ressources, {ForumTopic.objects.count()} discussions. Compte étudiant : tekeng@gmail.com.'
        ))

    def upsert_user(self, email, first_name, last_name, role):
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            user = User(username=email, email=email)
        user.first_name, user.last_name, user.email, user.is_active = first_name, last_name, email, True
        user.set_password(self.seed_password)
        user.save()
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role, profile.status = role, 'active'
        profile.save(update_fields=['role', 'status'])
        return user

    def lesson_content(self, lesson_title, module_title, subject):
        return (
            f"LEÇON — {lesson_title}\n\n"
            f"Objectif\nComprendre la place de « {lesson_title} » dans le thème « {module_title} » et être capable de la mobiliser dans une réponse de concours.\n\n"
            f"1. Définir la notion\nCommencez par formuler une définition précise avec vos propres mots. Identifiez ensuite les termes proches qu’il ne faut pas confondre. En {subject}, une définition utile doit préciser le cadre, la fonction de la notion et ses principales limites.\n\n"
            f"2. Situer la notion dans le programme\nReliez cette notion aux autres éléments du module « {module_title} ». Recherchez dans le programme publié les thèmes associés, puis construisez une carte simple : définition, fondement, mécanisme, exemple et limite.\n\n"
            f"3. Méthode pour l’épreuve\nDans une question courte, répondez d’abord directement, puis justifiez. Dans une composition, utilisez la notion pour construire un argument et non comme une simple récitation. Chaque paragraphe doit comporter une idée, une explication et une illustration vérifiable.\n\n"
            f"À retenir\n• définir avant de discuter ;\n• distinguer la règle, son application et ses limites ;\n• rattacher l’argument au sujet exact ;\n• vérifier les informations réglementaires dans la source liée au cours.\n\n"
            f"Exercice d’application\nRédigez en huit lignes une explication de « {lesson_title} ». Ajoutez un exemple et terminez par une limite ou une précaution. Comparez ensuite votre réponse au programme officiel associé."
        )

    def upsert_content(self, slug, kind, title, concours, author, data, source_name, source_url):
        item, _ = LearningContent.objects.update_or_create(
            slug=slug,
            defaults={'kind': kind, 'title': title, 'concourse': concours, 'author': author, 'data': data,
                      'status': 'published', 'is_private': False, 'source_name': source_name,
                      'source_url': source_url, 'verified_at': timezone.now()},
        )
        return item

    def upsert_quiz(self, slug, concours, author, title, questions, source_url):
        return self.upsert_content(slug, 'quiz_bank', title, concours, author, {
            'config': {'concourseId': concours.id_code, 'title': title, 'durationMinutes': 20,
                       'questionCount': len(questions), 'passingScore': 60, 'concourse': concours.title},
            'questions': questions,
        }, 'Simulation pédagogique fondée sur le programme publié', source_url)

    def upsert_exam(self, slug, concours, author, title, questions, source_url):
        epreuves, oral, official_structure, notice = self.exam_structure(slug, concours, questions)
        return self.upsert_content(slug, 'exam', title, concours, author, {
            'id': slug, 'concourseId': concours.id_code, 'concourse': concours.title, 'title': title,
            'description': 'Session complète : consignes, barèmes, chronomètre, correction automatique formative et corrigés structurés.',
            'passingScore': 60, 'epreuves': epreuves, 'oral': oral,
            'officialStructure': official_structure, 'structureNotice': notice,
        }, 'Simulation pédagogique fondée sur le programme publié', source_url)

    def exam_structure(self, slug, concours, questions):
        subjects = list(concours.subjects or concours.modules or ['Culture générale', 'Matière de spécialité'])

        def written(key, title, subject, kind, duration, coefficient, thesis, expectations, sections=None, **extra):
            return {
                'id': f'{slug}-{key}', 'title': title, 'subject': subject, 'type': kind,
                'durationMinutes': duration, 'coefficient': coefficient, 'totalPoints': 20,
                'instructions': [
                    'Lisez entièrement le sujet avant de commencer.',
                    'Respectez la structure demandée et justifiez chaque réponse.',
                    'Relisez la copie avant la soumission définitive.',
                ],
                'sections': sections or [
                    {'title': 'Compréhension et problématique', 'points': 4, 'description': 'Définition des termes et identification de l’enjeu.'},
                    {'title': 'Développement argumenté', 'points': 12, 'description': 'Organisation, connaissances, démonstration et exemples.'},
                    {'title': 'Conclusion et qualité de la langue', 'points': 4, 'description': 'Réponse finale, clarté et présentation.'},
                ],
                'thesis': thesis, 'correction': expectations,
                'modelAnswer': f'Plan indicatif :\n1. Définir et délimiter le sujet.\n2. Construire une démonstration en deux parties équilibrées.\n3. Mobiliser {subject} avec des exemples vérifiables.\n4. Répondre clairement à la problématique en conclusion.',
                **extra,
            }

        def qcm(key, title, subject, duration, coefficient, subset=None):
            return {
                'id': f'{slug}-{key}', 'title': title, 'subject': subject, 'type': 'qcm',
                'durationMinutes': duration, 'coefficient': coefficient, 'totalPoints': 20,
                'instructions': ['Une seule réponse est correcte par question.', 'Une réponse non renseignée vaut zéro point.', 'Vous pouvez revenir sur une question avant la soumission.'],
                'sections': [{'title': 'Questions objectives', 'points': 20, 'description': 'Notation proportionnelle au nombre de réponses exactes.'}],
                'questions': subset or questions,
            }

        def oral_block():
            oral_questions = [
                {'id': 1, 'text': f'Présentez votre motivation pour intégrer {concours.title}.', 'category': 'Grand oral — coefficient 1',
                 'suggestedAnswer': 'Présenter un projet cohérent, les qualités mobilisables et une connaissance concrète du service public.', 'timeLimitSeconds': 600},
                {'id': 2, 'text': 'Répondez dans votre seconde langue officielle puis développez brièvement votre projet professionnel.', 'category': 'Oral de langue — coefficient 1',
                 'suggestedAnswer': 'Réponse structurée, vocabulaire professionnel, phrases simples et argument personnel.', 'timeLimitSeconds': 600},
            ]
            return {'title': 'Admission — grand oral et oral de langue', 'durationMinutes': 20, 'coefficient': 2, 'questions': oral_questions}

        code = concours.id_code
        if code in {'enam-2026-admin-a', 'enam-2026-admin-b'}:
            epreuves = [
                written('culture', 'Culture générale', 'Culture générale', 'dissertation', 240, 4,
                        'Les transformations numériques améliorent-elles nécessairement la qualité du service public ?',
                        'Définition des termes, analyse équilibrée des gains et risques, exemples camerounais ou africains, conclusion nuancée.'),
                written('constitutionnel', 'Droit constitutionnel', 'Droit constitutionnel', 'dissertation', 240, 3,
                        'La séparation des pouvoirs garantit-elle à elle seule l’État de droit ?',
                        'Institutions, équilibre des pouvoirs, mécanismes de contrôle, limites et contextualisation.'),
                written('economie', 'Économie générale', 'Économie', 'questions_courtes', 240, 2,
                        'Traitez successivement : inflation et pouvoir d’achat ; emploi et croissance ; rôle économique de l’État.',
                        'Trois réponses distinctes, définitions exactes, mécanismes économiques et exemples.', [
                            {'title': 'Inflation et pouvoir d’achat', 'points': 7, 'description': 'Définition, causes, conséquences.'},
                            {'title': 'Emploi et croissance', 'points': 7, 'description': 'Relations, limites et politiques.'},
                            {'title': 'Intervention de l’État', 'points': 6, 'description': 'Objectifs, instruments et risques.'},
                        ]),
                written('specialite', 'Épreuve de spécialité — droit administratif', 'Droit administratif', 'cas_pratique', 240, 5,
                        'Une autorité administrative retire une décision individuelle favorable sans motivation. Analysez la légalité et les voies de recours.',
                        'Qualification des faits, règles applicables, application au cas, recours et conclusion opérationnelle.'),
            ]
            return epreuves, oral_block(), True, 'Structure reproduite d’après l’arrêté MINFOPRA 2026 lié : quatre écrits de 4 h (coefficients 4, 3, 2 et 5), puis grand oral et oral de langue.'

        if code in {'enam-2026-finances-a', 'enam-2026-finances-b'}:
            speciality = 'Comptabilité générale' if 'Comptabilité' in ' '.join(subjects) else 'Statistiques et économétrie'
            epreuves = [
                written('culture', 'Culture générale', 'Culture générale', 'dissertation', 240, 4,
                        'La modernisation des finances publiques est-elle d’abord une question de technologie ?',
                        'Problématique, gouvernance, contrôle, outils numériques, limites et exemples.'),
                written('constitutionnel', 'Droit constitutionnel', 'Droit constitutionnel', 'dissertation', 240, 2,
                        'Le contrôle de constitutionnalité protège-t-il efficacement les citoyens ?',
                        'Normes, institutions de contrôle, effets, limites et illustration.'),
                written('economie', 'Économie générale', 'Économie générale', 'questions_courtes', 240, 3,
                        'Analysez l’inflation, la politique budgétaire et les mécanismes de marché.',
                        'Définitions, mécanismes, liens entre les notions et exemples chiffrés ou contextualisés.'),
                written('specialite', f'Épreuve de spécialité — {speciality}', speciality, 'cas_pratique', 240, 5,
                        f'À partir d’une situation de gestion publique, présentez les calculs, contrôles et décisions relevant de {speciality}.',
                        'Démarche, calculs ou indicateurs, justification et contrôle du résultat.'),
            ]
            return epreuves, oral_block(), True, 'Structure reproduite d’après l’arrêté MINFOPRA 2026 lié : Culture générale, Droit constitutionnel, Économie générale et spécialité, toutes sur 4 h, coefficients 4, 2, 3 et 5.'

        if code == 'enam-2026-justice':
            epreuves = [
                written('culture', 'Culture générale', 'Culture générale', 'dissertation', 240, 2,
                        'La confiance dans la justice dépend-elle principalement de la célérité des procédures ?',
                        'Accès au droit, qualité, indépendance, célérité, garanties procédurales et conclusion.'),
                written('specialite-1', 'Spécialité 1 — Droit pénal et procédure pénale', 'Droit pénal', 'cas_pratique', 240, 4,
                        'Qualifiez les faits d’une procédure pénale, identifiez les éléments de l’infraction et les garanties applicables.',
                        'Qualification, texte applicable, procédure, droits des parties et solution.'),
                written('specialite-2', 'Spécialité 2 — Droit civil et procédure civile', 'Droit civil', 'cas_pratique', 240, 5,
                        'Analysez un litige contractuel : compétence, recevabilité, obligations des parties et réparation.',
                        'Faits pertinents, problème juridique, règles, application et solution.'),
                written('specialite-3', 'Spécialité 3 — Droit des affaires', 'Droit des affaires', 'dissertation', 240, 3,
                        'La sécurité juridique est-elle une condition suffisante du développement des entreprises ?',
                        'Concepts, règles applicables, environnement économique, limites et propositions.'),
            ]
            return epreuves, oral_block(), True, 'Structure reproduite d’après l’arrêté MINFOPRA 2026 lié : Culture générale et trois spécialités de 4 h, coefficients 2, 4, 5 et 3, puis deux oraux.'

        if code in {'enam-2026-greffes-a', 'enam-2026-greffes-b'}:
            epreuves = [
                written('culture', 'Culture générale', 'Culture générale', 'dissertation', 240, 2,
                        'La dématérialisation peut-elle rapprocher durablement la justice du citoyen ?',
                        'Accès, efficacité, sécurité, fracture numérique et garanties.'),
                written('droit-public', 'Droit public', subjects[1] if len(subjects) > 1 else 'Droit public', 'dissertation', 240, 4,
                        'Présentez les principes qui encadrent l’organisation et l’action des institutions publiques.',
                        'Plan juridique, sources, institutions, principes et limites.'),
                written('procedure', 'Procédure et pratique du greffe', subjects[2] if len(subjects) > 2 else 'Procédure', 'cas_pratique', 240, 5,
                        'À partir d’un dossier contentieux, établissez les formalités, actes, délais et contrôles relevant du greffe.',
                        'Chronologie, compétence, actes, délais, conservation et information des parties.'),
            ]
            return epreuves, oral_block(), True, 'Structure alignée sur l’arrêté MINFOPRA 2026 des greffes lié à la fiche ; les matières et coefficients doivent être revérifiés dans le PDF de la section choisie.'

        if code == 'iai-cameroun-2026-travaux':
            epreuves = [
                qcm('aptitudes', 'Aptitudes numériques, logique et raisonnement', 'Mathématiques et logique', 90, 2, questions[:8]),
                written('algorithmique', 'Algorithmique et programmation', 'Algorithmique et programmation', 'code', 120, 3,
                        'Écrivez une fonction Python qui reçoit une liste d’adresses IPv4, ignore les valeurs invalides et retourne le nombre d’adresses privées valides par sous-réseau /24.',
                        'Décomposition du problème, validation IPv4, reconnaissance des plages privées, résultat exact, cas limites et lisibilité.',
                        sections=[
                            {'title': 'Analyse et algorithme', 'points': 5, 'description': 'Entrées, sorties, cas limites et démarche.'},
                            {'title': 'Exactitude fonctionnelle', 'points': 10, 'description': 'Validation, filtrage et comptage corrects.'},
                            {'title': 'Qualité du code', 'points': 5, 'description': 'Fonctions, noms, lisibilité et justification.'},
                        ], language='python', starterCode='def compter_adresses_privees_par_reseau(adresses):\n    # Retourner un dictionnaire {"192.168.1": nombre}\n    pass'),
                written('reseaux', 'Systèmes, réseaux et génie logiciel', 'Systèmes et réseaux', 'questions_courtes', 120, 2,
                        'Répondez successivement : rôle de TCP et IP ; différence entre authentification et autorisation ; étapes essentielles d’un cycle de développement logiciel.',
                        'Réponses distinctes, vocabulaire technique exact, exemple concret et limites.', [
                            {'title': 'Architecture réseau', 'points': 7, 'description': 'Adressage, acheminement et transport fiable.'},
                            {'title': 'Sécurité', 'points': 6, 'description': 'Identité, droits et principe du moindre privilège.'},
                            {'title': 'Génie logiciel', 'points': 7, 'description': 'Analyse, conception, réalisation, tests et maintenance.'},
                        ]),
            ]
            oral = {
                'title': 'Entretien de motivation — simulation pédagogique', 'durationMinutes': 15, 'coefficient': 1,
                'questions': [
                    {'id': 1, 'text': 'Pourquoi souhaitez-vous intégrer l’IAI-Cameroun et quelle option visez-vous ?', 'category': 'Motivation', 'suggestedAnswer': 'Relier le projet professionnel à la formation et à une option précise.', 'timeLimitSeconds': 180},
                    {'id': 2, 'text': 'Présentez un problème informatique que vous avez résolu ou aimeriez résoudre.', 'category': 'Projet', 'suggestedAnswer': 'Décrire le besoin, la méthode, les difficultés et le résultat attendu.', 'timeLimitSeconds': 180},
                ],
            }
            return epreuves, oral, False, (
                'Simulation pédagogique construite pour les options Génie logiciel et Systèmes et réseaux. '
                'La date, les options et les conditions viennent de la publication IAI-Cameroun 2026 ; '
                'le détail des épreuves doit être confirmé dans le communiqué de chaque session.'
            )

        primary, secondary, third = subjects[0], subjects[min(1, len(subjects) - 1)], subjects[min(2, len(subjects) - 1)]
        technical = any(token in f'{concours.category} {" ".join(subjects)}'.lower() for token in ['informatique', 'numérique', 'technologie'])
        epreuves = [
            qcm('fondamentaux', f'Fondamentaux — {primary}', primary, 90, 2, questions[:6]),
            written('composition', f'Composition — {secondary}', secondary, 'dissertation', 180, 3,
                    f'Traitez de manière structurée un enjeu majeur de {secondary} en lien avec {concours.title}.',
                    'Définition, problématique, connaissances du programme, exemples et conclusion.'),
        ]
        if technical:
            epreuves.append(written('technique', f'Atelier technique — {third}', third, 'code', 120, 2,
                    'Écrivez une fonction Python qui reçoit une liste de notes, vérifie les valeurs, puis retourne la moyenne et le nombre de notes supérieures ou égales à 10.',
                    'Validation des entrées, calcul exact, fonction réutilisable, gestion du cas vide et lisibilité.',
                    sections=[
                        {'title': 'Validation des données', 'points': 4, 'description': 'Cas vide et valeurs invalides.'},
                        {'title': 'Algorithme et résultat', 'points': 10, 'description': 'Moyenne et comptage corrects.'},
                        {'title': 'Qualité du code', 'points': 6, 'description': 'Fonction, lisibilité et explications.'},
                    ], language='python', starterCode='def analyser_notes(notes):\n    # Retourner {"moyenne": ..., "admis": ...}\n    pass',
                    modelAnswer='def analyser_notes(notes):\n    if not notes:\n        return {"moyenne": 0, "admis": 0}\n    if any(not isinstance(note, (int, float)) or note < 0 or note > 20 for note in notes):\n        raise ValueError("Chaque note doit être comprise entre 0 et 20")\n    return {"moyenne": sum(notes) / len(notes), "admis": sum(note >= 10 for note in notes)}'))
        else:
            epreuves.append(written('application', f'Application — {third}', third, 'cas_pratique', 120, 2,
                    f'Analysez une situation concrète relevant de {third}, puis proposez une solution justifiée.',
                    'Identification des faits, méthode, application des connaissances et solution argumentée.'))
        return epreuves, None, False, 'Structure pédagogique réaliste construite avec les matières publiées. Les durées et coefficients sont des paramètres de simulation à comparer à l’arrêté de la spécialité choisie.'

    def populate_iai_content(self, iai, teachers):
        """Ajoute un parcours IAI dense, idempotent et clairement séparé des informations officielles."""
        source = IAI_CAMEROUN_2026

        def questions(rows, offset=0):
            return [
                {'id': offset + index, 'question': question, 'options': options, 'correctAnswer': answer,
                 'explanation': explanation, 'subject': subject}
                for index, (question, options, answer, explanation, subject) in enumerate(rows, start=1)
            ]

        bank_a = questions([
            ('Quelle est la complexité d’une recherche linéaire dans une liste de n éléments ?', ['O(1)', 'O(log n)', 'O(n)', 'O(n²)'], 2, 'Dans le pire cas, chaque élément est examiné une fois : la complexité est O(n).', 'Algorithmique'),
            ('Quel mot-clé Python renvoie une valeur depuis une fonction ?', ['yield uniquement', 'return', 'print', 'break'], 1, 'return termine l’appel de fonction et transmet une valeur au code appelant.', 'Programmation'),
            ('Dans le modèle relationnel, une clé primaire sert à :', ['Identifier chaque ligne de façon unique', 'Chiffrer la table', 'Créer une sauvegarde', 'Trier automatiquement'], 0, 'La clé primaire impose une identité unique et non nulle à chaque enregistrement.', 'Bases de données'),
            ('Quel protocole fournit un transport fiable et ordonné ?', ['IP', 'UDP', 'TCP', 'ARP'], 2, 'TCP numérote, acquitte et retransmet les segments afin de fournir un flux fiable et ordonné.', 'Réseaux'),
            ('Le principe du moindre privilège consiste à :', ['Donner tous les droits', 'Accorder seulement les droits nécessaires', 'Supprimer les mots de passe', 'Partager un compte'], 1, 'Un utilisateur ou service ne reçoit que les permissions indispensables à sa mission.', 'Cybersécurité'),
            ('Si f(x)=x²+3x, alors f’(x) vaut :', ['2x+3', 'x+3', '2x', 'x²'], 0, 'La dérivée de x² est 2x et celle de 3x est 3.', 'Mathématiques'),
            ('Une adresse IPv4 comporte :', ['16 bits', '32 bits', '64 bits', '128 bits'], 1, 'IPv4 utilise 32 bits, généralement affichés en quatre octets décimaux.', 'Réseaux'),
            ('Un test unitaire vérifie principalement :', ['Une petite unité de code isolée', 'Tout le réseau physique', 'Le recrutement', 'La mise en page papier'], 0, 'Le test unitaire contrôle une fonction ou un composant dans un contexte maîtrisé.', 'Génie logiciel'),
            ('Choose the correct sentence:', ['The program run correctly.', 'The program runs correctly.', 'The program running correctly.', 'The program runnings correctly.'], 1, 'With the third-person singular subject “program”, the present verb is “runs”.', 'Anglais technique'),
            ('Une probabilité doit être comprise entre :', ['-1 et 1', '0 et 1', '0 et 1000', '-∞ et +∞'], 1, 'Par définition, la probabilité d’un événement appartient à l’intervalle [0,1].', 'Mathématiques'),
        ])
        bank_b = questions([
            ('Une pile suit quel principe ?', ['FIFO', 'LIFO', 'Aléatoire', 'Par priorité uniquement'], 1, 'La dernière valeur empilée est la première retirée : Last In, First Out.', 'Algorithmique'),
            ('Quelle requête lit des lignes dans une table SQL ?', ['SELECT', 'UPDATE', 'DELETE', 'DROP'], 0, 'SELECT interroge une ou plusieurs tables sans modifier les données.', 'Bases de données'),
            ('Le masque 255.255.255.0 correspond au préfixe :', ['/8', '/16', '/24', '/32'], 2, 'Trois octets à 255 représentent 24 bits positionnés à 1.', 'Réseaux'),
            ('L’authentification répond à la question :', ['Qui êtes-vous ?', 'Quels droits avez-vous ?', 'Quel câble utiliser ?', 'Quelle table supprimer ?'], 0, 'L’authentification vérifie l’identité ; l’autorisation détermine ensuite les actions permises.', 'Cybersécurité'),
            ('Quel mécanisme évite de répéter le même code ?', ['Une fonction réutilisable', 'Une variable globale obligatoire', 'Une capture d’écran', 'Un commentaire vide'], 0, 'Une fonction correctement paramétrée factorise un traitement et facilite les tests.', 'Programmation'),
            ('Dans une matrice A de dimension 2×3, le nombre d’éléments est :', ['5', '6', '8', '9'], 1, 'Deux lignes multipliées par trois colonnes donnent six éléments.', 'Mathématiques'),
            ('Quel document décrit les besoins attendus d’un logiciel ?', ['Le cahier des charges', 'Le cache DNS', 'La table ARP', 'Le bytecode'], 0, 'Le cahier des charges formalise les objectifs, fonctions, contraintes et critères d’acceptation.', 'Génie logiciel'),
            ('DNS sert principalement à :', ['Associer des noms à des adresses IP', 'Compiler Python', 'Chiffrer un disque', 'Créer une table SQL'], 0, 'DNS résout notamment les noms de domaine en adresses IP.', 'Réseaux'),
            ('“Data integrity” signifie :', ['Intégrité des données', 'Vitesse du processeur', 'Taille du clavier', 'Couleur du réseau'], 0, 'Data integrity désigne l’exactitude et la cohérence des données pendant leur cycle de vie.', 'Anglais technique'),
            ('Une sauvegarde fiable doit idéalement être :', ['Unique et toujours connectée', 'Testée et conservée sur plusieurs supports', 'Sans contrôle de restauration', 'Dans le même dossier uniquement'], 1, 'Une sauvegarde utile est redondante, séparée et régulièrement testée par restauration.', 'Cybersécurité'),
        ], offset=100)

        quiz_a = self.upsert_quiz('quiz-iai-cameroun-2026-serie-a', iai, teachers[0], 'Quiz IAI-Cameroun — Série A', bank_a, source)
        quiz_b = self.upsert_quiz('quiz-iai-cameroun-2026-serie-b', iai, teachers[1], 'Quiz IAI-Cameroun — Série B', bank_b, source)
        exam_a = self.upsert_exam('exam-iai-cameroun-2026-serie-a', iai, teachers[0], 'Examen blanc IAI-Cameroun — Série A complète', bank_a, source)
        exam_b = self.upsert_exam('exam-iai-cameroun-2026-serie-b', iai, teachers[1], 'Examen blanc IAI-Cameroun — Série B complète', bank_b, source)

        technical_modules = [
            ('Algorithmique fondamentale', [
                ('Variables, conditions et boucles', 'Une variable mémorise une valeur. Une condition choisit un chemin selon une expression booléenne. Une boucle répète un traitement ; sa condition d’arrêt doit être explicite.'),
                ('Fonctions et décomposition', 'Une fonction reçoit des paramètres et retourne un résultat. Décomposer un problème en fonctions courtes améliore la lisibilité, les tests et la réutilisation.'),
                ('Complexité et cas limites', 'La complexité estime l’évolution du coût avec la taille des données. Toujours traiter les entrées vides, invalides, minimales et maximales.'),
            ]),
            ('Réseaux et systèmes', [
                ('Adressage IPv4 et sous-réseaux', 'IPv4 utilise 32 bits. Le préfixe CIDR indique les bits réseau ; /24 correspond au masque 255.255.255.0. Une passerelle relie le sous-réseau aux autres réseaux.'),
                ('TCP, UDP, DNS et HTTP', 'IP achemine, TCP fiabilise, UDP réduit la surcharge, DNS résout les noms et HTTP organise les échanges applicatifs du Web.'),
                ('Sécurité opérationnelle', 'Protéger un système exige mises à jour, mots de passe robustes, moindre privilège, journalisation, sauvegardes isolées et tests de restauration.'),
            ]),
            ('Génie logiciel et données', [
                ('Cycle de développement', 'Un cycle maîtrisé relie besoin, spécifications, conception, code, tests, déploiement et maintenance. Chaque exigence doit pouvoir être vérifiée.'),
                ('Modèle relationnel et SQL', 'Une table possède des colonnes typées et des lignes. Les clés primaires identifient ; les clés étrangères relient ; les contraintes garantissent la cohérence.'),
                ('Stratégie de tests', 'Les tests unitaires ciblent une unité, les tests d’intégration vérifient les interactions et les tests de bout en bout reproduisent un parcours utilisateur.'),
            ]),
        ]
        modules = []
        for module_index, (module_title, lessons) in enumerate(technical_modules, start=1):
            modules.append({
                'id': f'course-iai-core-m{module_index}', 'title': module_title,
                'lessons': [
                    {'id': f'course-iai-core-m{module_index}-l{lesson_index}', 'title': title, 'type': 'article',
                     'duration': '25 min', 'completed': False, 'summary': content, 'content': (
                         f'LEÇON — {title}\n\n{content}\n\nMéthode concours\nDéfinissez la notion, expliquez son mécanisme, donnez un exemple puis traitez un cas limite.\n\n'
                         f'Exercice\nRédigez une réponse en dix lignes sur « {title} », puis créez un exemple technique et vérifiez-le.'
                     ), 'url': source, 'videoUrl': '', 'documentUrl': ''}
                    for lesson_index, (title, content) in enumerate(lessons, start=1)
                ],
            })
        core_course = self.upsert_content(
            'course-iai-cameroun-fondamentaux-informatique', 'course', 'Fondamentaux informatiques — préparation IAI-Cameroun',
            iai, teachers[0], {'subject': 'Informatique', 'instructor': teachers[0].get_full_name(),
                              'description': 'Neuf leçons techniques avec exercices pour les options Génie logiciel et Systèmes et réseaux.',
                              'level': 'Progressif', 'duration': '225 min', 'lessonsCount': 9, 'progress': 0, 'modules': modules},
            'Parcours pédagogique basé sur les options publiées par IAI-Cameroun', source,
        )

        oral = self.upsert_content('oral-iai-cameroun-2026-entretien', 'oral_bank', 'Entretien blanc IAI-Cameroun', iai, teachers[2], {
            'questions': [
                {'id': 1, 'number': 1, 'total': 5, 'text': 'Présentez votre parcours et votre projet informatique.', 'category': 'Motivation', 'timeLimitSeconds': 120},
                {'id': 2, 'number': 2, 'total': 5, 'text': 'Pourquoi choisissez-vous Génie logiciel ou Systèmes et réseaux ?', 'category': 'Orientation', 'timeLimitSeconds': 120},
                {'id': 3, 'number': 3, 'total': 5, 'text': 'Expliquez simplement le rôle d’une adresse IP.', 'category': 'Technique', 'timeLimitSeconds': 120},
                {'id': 4, 'number': 4, 'total': 5, 'text': 'Décrivez votre méthode pour résoudre un problème algorithmique.', 'category': 'Méthode', 'timeLimitSeconds': 120},
                {'id': 5, 'number': 5, 'total': 5, 'text': 'Comment réagissez-vous lorsqu’un programme ne fonctionne pas ?', 'category': 'Raisonnement', 'timeLimitSeconds': 120},
            ],
        }, 'Simulation pédagogique liée aux options IAI-Cameroun', source)

        phases = [
            ('dossier', 'Sécuriser le dossier IAI-Cameroun', [
                ('Vérifier l’option et les conditions de diplôme', 'reading', core_course.id),
                ('Consulter la publication officielle de la session', 'reading', core_course.id),
                ('Contrôler les pièces et échéances', 'reading', core_course.id),
            ]),
            ('fondamentaux', 'Valider les fondamentaux techniques IAI', [
                ('Terminer les neuf leçons techniques', 'reading', core_course.id),
                ('Passer le quiz Série A', 'quiz', quiz_a.id),
                ('Passer le quiz Série B', 'quiz', quiz_b.id),
            ]),
            ('simulation', 'Finaliser la préparation IAI', [
                ('Composer l’examen blanc Série A', 'paper', exam_a.id),
                ('Composer l’examen blanc Série B', 'paper', exam_b.id),
                ('Faire l’entretien blanc', 'oral', oral.id),
            ]),
        ]
        for number, (key, title, tasks) in enumerate(phases, start=1):
            self.upsert_content(f'checkpoint-iai-cameroun-{key}', 'checkpoint', title, iai, teachers[number % 3], {
                'number': number, 'description': f'Étape structurée du parcours {iai.title}.', 'concourse': iai.title,
                'status': 'in_progress', 'progressPercent': 0, 'badgeAwarded': f'IAI — étape {number}',
                'tasks': [{'id': f'iai-{key}-{index}', 'title': task, 'type': task_type, 'completed': False,
                           'points': round(100 / len(tasks)), 'contentId': content_id}
                          for index, (task, task_type, content_id) in enumerate(tasks, start=1)],
            }, 'Parcours pédagogique IAI-Cameroun', source)

        Resource.objects.update_or_create(
            title='Publication du concours IAI-Cameroun 2026-2027',
            defaults={'concourse': iai, 'concourse_name': iai.title, 'type': 'fiche', 'file_name': 'concours-iai-cameroun-2026',
                      'url': source, 'metadata': {'subject': 'Admission', 'description': 'Page IAI-Cameroun associée au concours.',
                                                  'session': iai.session, 'year': 2026, 'tags': ['source officielle', 'admission']},
                      'author': teachers[0], 'status': 'published'},
        )
        Resource.objects.update_or_create(
            title='Préinscription numérique IAI-Cameroun — informations 2026-2027',
            defaults={'concourse': iai, 'concourse_name': iai.title, 'type': 'fiche', 'file_name': 'preinscription-iai-2026',
                      'url': IAI_CAMEROUN_ADMISSIONS, 'metadata': {'subject': 'Dossier', 'description': 'Informations de préinscription publiées avec IAI-Cameroun parmi les établissements d’accueil.',
                                                                  'session': iai.session, 'year': 2026, 'tags': ['préinscription', 'dossier']},
                      'author': teachers[1], 'status': 'published'},
        )

    def populate_every_concours(self, teachers):
        """Garantit un parcours complet et idempotent pour chaque fiche active."""
        fallback_subjects = {
            'administr': ['Culture générale', 'Droit public', 'Économie'],
            'justice': ['Culture générale', 'Droit civil', 'Droit pénal'],
            'finance': ['Culture générale', 'Finances publiques', 'Économie'],
            'enseign': ['Culture générale', 'Pédagogie', 'Matière de spécialité'],
            'techn': ['Mathématiques', 'Informatique', 'Culture générale'],
            'ingén': ['Mathématiques', 'Physique', 'Culture générale'],
            'commerce': ['Culture générale', 'Économie', 'Mathématiques'],
            'jeunesse': ['Culture générale', 'Jeunesse et animation', 'Méthodologie'],
            'sport': ['Culture générale', 'Éducation physique et sportive', 'Méthodologie'],
        }
        all_concours = list(Concours.objects.filter(active=True).order_by('title'))
        categories = list(dict.fromkeys(item.category for item in all_concours))
        titles = [item.title for item in all_concours]

        for contest_index, concours in enumerate(all_concours):
            subjects = list(concours.subjects or concours.modules or [])
            if not subjects:
                key = f'{concours.category} {concours.title}'.lower()
                subjects = next((value for token, value in fallback_subjects.items() if token in key), ['Culture générale', 'Méthodologie', 'Matière de spécialité'])
                concours.subjects = subjects
                concours.modules = subjects
                concours.save(update_fields=['subjects', 'modules'])
            source_url = concours.source_url
            author = teachers[contest_index % len(teachers)]
            created_courses = []
            for subject_index, subject in enumerate(subjects, start=1):
                slug = f"course-{concours.id_code}-{slugify(subject)[:45]}"
                module_specs = [
                    (f'Comprendre le programme de {subject}', [f'Notions fondamentales de {subject}', f'Vocabulaire essentiel de {subject}', f'Liens avec le programme du concours']),
                    (f'S’entraîner en {subject}', [f'Méthode de réponse en {subject}', f'Application guidée en {subject}', f'Autoévaluation en {subject}']),
                ]
                modules = []
                for module_number, (module_title, lessons) in enumerate(module_specs, start=1):
                    rows = []
                    for lesson_number, lesson_title in enumerate(lessons, start=1):
                        video_url = self.subject_video(subject) if module_number == 1 and lesson_number == 1 else ''
                        rows.append({
                            'id': f'{slug}-m{module_number}-l{lesson_number}', 'title': lesson_title,
                            'type': 'video' if video_url else ('exercise' if lesson_number == 3 else 'article'), 'duration': '20 min',
                            'completed': False, 'summary': f'Leçon pédagogique consacrée à {lesson_title}.',
                            'url': video_url or source_url, 'videoUrl': video_url,
                            'documentUrl': source_url if source_url.lower().endswith('.pdf') else '',
                            'content': self.lesson_content(lesson_title, module_title, subject),
                        })
                    modules.append({'id': f'{slug}-m{module_number}', 'title': module_title, 'lessons': rows})
                course = self.upsert_content(slug, 'course', f'{subject} — {concours.title}', concours, author, {
                    'subject': subject, 'instructor': author.get_full_name(),
                    'description': 'Cours de préparation construit à partir des matières affichées dans la fiche du concours.',
                    'level': 'Progressif', 'duration': '120 min', 'lessonsCount': 6, 'progress': 0, 'modules': modules,
                }, concours.source_name or 'Fiche officielle du concours', source_url)
                created_courses.append(course)

                self.upsert_content(f'flashcard-{concours.id_code}-{subject_index}', 'flashcard', f'{subject} — repère {subject_index}', concours, author, {
                    'subject': subject, 'front': f'Comment travailler efficacement {subject} pour ce concours ?',
                    'back': 'Identifier les notions du programme, les définir, s’entraîner avec une réponse structurée puis analyser ses erreurs.',
                    'category': concours.title, 'mastered': False,
                }, 'Contenu pédagogique associé à la fiche du concours', source_url)

            questions = self.catalogue_questions(concours, all_concours, categories, titles)
            quiz = self.upsert_quiz(f'quiz-auto-{concours.id_code}', concours, author, f'Quiz de repérage — {concours.title}', questions, source_url)
            exam = self.upsert_exam(f'exam-auto-{concours.id_code}', concours, author, f'Examen blanc complet — {concours.title}', questions, source_url)
            oral_questions = [
                f'Présentez votre motivation pour le concours {concours.title}.',
                f'Expliquez votre méthode de préparation pour la matière {subjects[0]}.',
                'Donnez un exemple de difficulté rencontrée et expliquez comment vous l’avez surmontée.',
            ]
            oral = self.upsert_content(f'oral-auto-{concours.id_code}', 'oral_bank', f'Entraînement oral — {concours.title}', concours, author, {
                'questions': [{'id': index, 'number': index, 'total': len(oral_questions), 'text': text, 'category': 'Motivation et méthode', 'timeLimitSeconds': 120} for index, text in enumerate(oral_questions, start=1)],
            }, 'Banque pédagogique associée au concours', source_url)

            for course_number, course in enumerate(created_courses, start=1):
                self.upsert_content(f'checkpoint-{course.slug}', 'checkpoint', f'Checkpoint — {course.title}', concours, author, {
                    'number': course_number, 'description': f'Parcours automatique lié au cours « {course.title} ».',
                    'concourse': concours.title, 'status': 'in_progress', 'progressPercent': 0,
                    'badgeAwarded': f'{subjects[min(course_number - 1, len(subjects) - 1)]} validé',
                    'tasks': [
                        {'id': f'{course.slug}-read', 'title': 'Terminer les six leçons du cours', 'type': 'reading', 'completed': False, 'points': 40, 'contentId': course.id},
                        {'id': f'{course.slug}-quiz', 'title': 'Passer le quiz de repérage', 'type': 'quiz', 'completed': False, 'points': 25, 'contentId': quiz.id},
                        {'id': f'{course.slug}-exam', 'title': 'Passer l’examen blanc', 'type': 'paper', 'completed': False, 'points': 25, 'contentId': exam.id},
                        {'id': f'{course.slug}-oral', 'title': 'Faire une simulation orale', 'type': 'oral', 'completed': False, 'points': 10, 'contentId': oral.id},
                    ],
                }, 'Parcours pédagogique associé au concours', source_url)

            Resource.objects.update_or_create(
                title=f'Fiche officielle — {concours.title}',
                defaults={'concourse': concours, 'concourse_name': concours.title, 'type': 'pdf' if source_url.lower().endswith('.pdf') else 'fiche',
                          'file_name': source_url.rsplit('/', 1)[-1] or concours.id_code, 'url': source_url,
                          'metadata': {'subject': 'Programme et inscription', 'description': 'Lien vers la publication enregistrée pour ce concours.', 'session': concours.session,
                                       'year': 2026, 'contentPreview': concours.description or '', 'correctionText': '', 'tags': ['source officielle']},
                          'author': author, 'status': 'published'},
            )
            Resource.objects.update_or_create(
                title=f'Sujet d’entraînement corrigé — {concours.title}',
                defaults={'concourse': concours, 'concourse_name': concours.title, 'type': 'pdf',
                          'file_name': f'entrainement-{concours.id_code}.pdf', 'url': source_url,
                          'metadata': {'subject': subjects[0], 'description': 'Sujet pédagogique, distinct d’une annale officielle.', 'session': concours.session,
                                       'year': 2026, 'duration': '2 h', 'durationMinutes': 120, 'coefficient': 2, 'questionsCount': 1,
                                       'contentPreview': f'Sujet pédagogique : présentez les notions essentielles de {subjects[0]} et montrez comment elles se rattachent au programme de {concours.title}.',
                                       'correctionText': f'Attendus : définition des notions, organisation logique, lien explicite avec {subjects[0]}, exemple pertinent et conclusion nuancée.',
                                       'tags': ['entraînement', 'corrigé']},
                          'author': author, 'status': 'published'},
            )
            contextual_video = next((self.subject_video(subject) for subject in subjects if self.subject_video(subject)), '')
            if contextual_video:
                Resource.objects.update_or_create(
                    title=f'Vidéo pédagogique africaine — {concours.title}',
                    defaults={'concourse': concours, 'concourse_name': concours.title, 'type': 'video',
                              'file_name': contextual_video.rsplit('=', 1)[-1], 'url': contextual_video,
                              'metadata': {'subject': subjects[0], 'description': 'Vidéo complémentaire issue d’un contexte éducatif africain ou camerounais.',
                                           'session': concours.session, 'tags': ['vidéo', 'Afrique', 'Cameroun']},
                              'author': author, 'status': 'published'},
                )

    def catalogue_questions(self, concours, all_concours, categories, titles):
        subjects = concours.subjects or concours.modules or ['Matière de spécialité']
        careers = concours.career_paths or ['Débouchés à vérifier dans la source']

        def options(correct, pool):
            values = [correct] + [value for value in pool if value != correct][:3]
            while len(values) < 4:
                values.append(f'Choix non retenu {len(values)}')
            rotation = len(concours.id_code) % 4
            values = values[rotation:] + values[:rotation]
            return values, values.index(correct)

        raw = [
            ('À quelle catégorie appartient cette fiche de concours ?', concours.category, categories),
            ('Quelle session est indiquée dans la fiche ?', concours.session, ['2025', '2025-2026', '2026', '2026-2027']),
            ('Quel intitulé correspond au parcours actuellement préparé ?', concours.title, titles),
            ('Quelle matière figure dans le programme enregistré ?', subjects[0], [s for item in all_concours for s in item.subjects]),
            ('Quel autre axe doit être révisé pour ce concours ?', subjects[min(1, len(subjects) - 1)], [s for item in all_concours for s in item.subjects]),
            ('Quel débouché est associé à la fiche ?', careers[0], [c for item in all_concours for c in item.career_paths]),
            ('Quelle démarche est fiable avant une inscription ?', 'Consulter la source officielle liée', ['Se fier à une rumeur', 'Ignorer la date limite', 'Inventer les pièces requises']),
            ('Quelle méthode convient pour une réponse rédigée ?', 'Définir, argumenter, illustrer et conclure', ['Réciter sans lien', 'Éviter le sujet', 'Ne pas relire']),
        ]
        result = []
        for index, (question, correct, pool) in enumerate(raw, start=1):
            choices, answer = options(correct, pool)
            result.append({'id': index, 'question': question, 'options': choices, 'correctAnswer': answer,
                           'explanation': f'La réponse « {correct} » provient de la fiche ou de la méthode pédagogique affichée.', 'subject': 'Repérage du programme'})
        return result

    def subject_video(self, subject):
        normalized = subject.lower()
        return next((url for token, url in AFRICAN_EDUCATION_VIDEOS.items() if token in normalized), '')

    def populate_forum(self, tekeng, teachers):
        specs = [
            ('Discussion d’accueil — organiser sa préparation ENAM', 'ENAM', teachers[2], 'Cette discussion d’initialisation sert à partager une méthode de planification hebdomadaire.'),
            ('Groupe de travail — pédagogie ENS', 'ENS', teachers[1], 'Cette discussion d’initialisation permet de poser des questions sur les objectifs et évaluations pédagogiques.'),
            ('Questions sur le dossier de candidature', 'Dossiers', tekeng, 'Quels éléments faut-il vérifier en priorité dans l’arrêté avant de déposer le dossier ?'),
        ]
        topics = []
        for title, category, author, content in specs:
            topic, _ = ForumTopic.objects.update_or_create(title=title, defaults={'category': category, 'author': author, 'content': content})
            topics.append(topic)
        replies = [
            (topics[0], tekeng, 'Je vais commencer par répartir les matières sur la semaine et réserver un créneau d’examen blanc.'),
            (topics[0], teachers[0], 'Bonne approche. Ajoutez un temps d’analyse des erreurs après chaque quiz.'),
            (topics[1], tekeng, 'Je souhaite travailler d’abord l’évaluation formative et la préparation de séquence.'),
            (topics[2], teachers[2], 'Vérifiez le diplôme requis, l’âge, la date limite, les pièces et le centre de dépôt directement dans la source officielle.'),
        ]
        for topic, author, content in replies:
            ForumReply.objects.get_or_create(topic=topic, author=author, content=content)

    def populate_messages(self, tekeng, teachers):
        welcome_messages = [
            'Message d’accueil automatique : je peux vous accompagner sur le droit public et les quiz ENAM.',
            'Message d’accueil automatique : je peux répondre à vos questions sur la pédagogie et le concours ENS.',
            'Message d’accueil automatique : je peux vous aider à structurer votre planning et vos compositions.',
        ]
        for teacher, message in zip(teachers, welcome_messages):
            TutorMessage.objects.get_or_create(sender=teacher, recipient=tekeng, text=message)
        TutorMessage.objects.get_or_create(sender=tekeng, recipient=teachers[0], text='Merci. Je commence par le module sur les sources du droit public.')
        TutorAppointment.objects.update_or_create(
            candidate=tekeng, tutor=teachers[1], topic='Point de méthode sur la préparation ENS',
            defaults={'scheduled_at': timezone.now() + timedelta(days=5), 'status': 'confirmed'},
        )

    def enam_questions(self):
        rows = [
            ('Quel principe impose à l’administration de respecter les normes qui lui sont supérieures ?', ['Principe de légalité', 'Principe de gratuité', 'Principe de rotation', 'Principe monétaire'], 0, 'Le principe de légalité soumet l’action administrative au droit.'),
            ('La décentralisation correspond principalement à :', ['La suppression des collectivités', 'Un transfert de compétences vers des collectivités autonomes', 'La privatisation de tous les services', 'La concentration des décisions'], 1, 'La décentralisation transfère des compétences à des collectivités dotées d’une autonomie administrative.'),
            ('Quel document prévoit et autorise les recettes et dépenses publiques ?', ['Le budget', 'Le registre civil', 'Le procès-verbal', 'Le contrat de travail'], 0, 'Le budget prévoit et autorise les recettes et les dépenses.'),
            ('Une hausse générale et durable du niveau des prix est appelée :', ['Décentralisation', 'Inflation', 'Jurisprudence', 'Déflation administrative'], 1, 'Il s’agit de l’inflation.'),
            ('Dans une dissertation, la problématique sert à :', ['Remplacer la conclusion', 'Organiser la question directrice', 'Lister les références', 'Éviter tout plan'], 1, 'La problématique formule la question directrice à laquelle la démonstration répond.'),
            ('Un service public poursuit prioritairement :', ['Un intérêt général', 'Un intérêt exclusivement privé', 'Une activité clandestine', 'Une sanction pénale'], 0, 'Le service public est lié à une mission d’intérêt général.'),
            ('Quel élément relie logiquement deux parties d’une composition ?', ['La transition', 'La signature', 'La pagination', 'Le brouillon'], 0, 'La transition clôt une partie et justifie la suivante.'),
            ('Le pouvoir réglementaire produit principalement :', ['Des actes réglementaires', 'Des diplômes universitaires', 'Des jugements civils', 'Des contrats privés uniquement'], 0, 'Le pouvoir réglementaire permet l’édiction de normes réglementaires.'),
            ('Le contrôle budgétaire porte notamment sur :', ['La gestion des recettes et dépenses', 'La météo', 'Les résultats sportifs', 'La littérature uniquement'], 0, 'Le contrôle budgétaire concerne l’exécution et la régularité des opérations financières publiques.'),
            ('Une bonne introduction de dissertation doit notamment :', ['Définir les termes et annoncer le plan', 'Donner uniquement la conclusion', 'Éviter la problématique', 'Accumuler des citations sans lien'], 0, 'L’introduction contextualise, définit, problématise et annonce la structure.'),
            ('La croissance économique désigne généralement :', ['Une augmentation durable de la production', 'Une baisse automatique des lois', 'Une réforme judiciaire', 'Une élection locale'], 0, 'La croissance mesure une augmentation durable de la production de biens et services.'),
            ('Le retrait d’un acte administratif consiste à :', ['Le faire disparaître dans les conditions prévues par le droit', 'Le traduire', 'Le publier deux fois', 'Le transformer en diplôme'], 0, 'Le retrait met fin rétroactivement à l’acte lorsque les conditions juridiques sont réunies.'),
        ]
        return [{'id': i, 'question': q, 'options': options, 'correctAnswer': answer, 'explanation': explanation, 'subject': 'Fondamentaux'} for i, (q, options, answer, explanation) in enumerate(rows, start=1)]

    def ens_questions(self):
        rows = [
            ('Une évaluation réalisée avant un apprentissage est dite :', ['Diagnostique', 'Terminale', 'Aléatoire', 'Budgétaire'], 0, 'L’évaluation diagnostique identifie les acquis et besoins initiaux.'),
            ('L’évaluation formative sert principalement à :', ['Ajuster l’apprentissage en cours', 'Supprimer toute rétroaction', 'Classer définitivement', 'Remplacer le cours'], 0, 'Elle fournit une rétroaction utile pendant l’apprentissage.'),
            ('Un objectif pédagogique observable précise :', ['Ce que l’apprenant devra pouvoir faire', 'Le salaire de l’enseignant', 'Le nom de l’établissement seulement', 'La date des vacances'], 0, 'Un objectif décrit un résultat observable attendu.'),
            ('La différenciation pédagogique consiste à :', ['Adapter les démarches aux besoins', 'Donner toujours la même tâche sans adaptation', 'Supprimer l’évaluation', 'Éviter toute interaction'], 0, 'Elle adapte supports, rythmes ou démarches à la diversité des apprenants.'),
            ('Dans un texte argumentatif, la thèse est :', ['L’idée principale défendue', 'Une faute de frappe', 'La date d’impression', 'Le numéro de page'], 0, 'La thèse est la position défendue par l’auteur.'),
            ('Un connecteur logique permet de :', ['Expliciter la relation entre les idées', 'Masquer le plan', 'Remplacer tous les verbes', 'Supprimer la ponctuation'], 0, 'Les connecteurs indiquent opposition, cause, conséquence ou progression.'),
            ('Une séquence pédagogique cohérente relie :', ['Objectifs, activités et évaluation', 'Uniquement le titre et la date', 'Le budget et la météo', 'La note sans consigne'], 0, 'L’alignement pédagogique relie objectifs, activités et évaluations.'),
            ('La remédiation intervient pour :', ['Traiter des difficultés identifiées', 'Punir automatiquement', 'Éviter toute correction', 'Raccourcir le nom du cours'], 0, 'La remédiation propose une aide ciblée après diagnostic des difficultés.'),
            ('Une consigne efficace doit être :', ['Claire et vérifiable', 'Ambiguë et implicite', 'Sans verbe d’action', 'Sans critère'], 0, 'Une consigne claire précise l’action et les critères attendus.'),
            ('La rétroaction pédagogique indique à l’apprenant :', ['Ses acquis et pistes de progression', 'Uniquement son identité', 'La météo du jour', 'Aucune information'], 0, 'Une rétroaction utile décrit les réussites et les améliorations possibles.'),
        ]
        return [{'id': i, 'question': q, 'options': options, 'correctAnswer': answer, 'explanation': explanation, 'subject': 'Pédagogie'} for i, (q, options, answer, explanation) in enumerate(rows, start=1)]
