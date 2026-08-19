from unittest.mock import patch
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from .models import ApiToken, Concours, LearningContent, UserProfile, StudySession


class ApiIntegrationTests(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_directory.cleanup)
        self.client = APIClient()
        self.concours = Concours.objects.create(
            id_code='verified-concours',
            title='Concours vérifié',
            category='Administration',
            session='2026',
            source_name='Organisme public',
            source_url='https://example.gov/concours',
        )

    def create_user(self, email, role, password='MotDePasse!2026'):
        user = User.objects.create_user(username=email, email=email, password=password, first_name=role.title())
        UserProfile.objects.create(user=user, role=role)
        token = ApiToken.issue(user)
        return user, token.key

    def authenticate(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_candidate_journey_persists_real_user_data(self):
        response = self.client.post('/api/auth/register/', {
            'name': 'Nouvelle Candidate',
            'email': 'candidate@example.org',
            'password': 'MotDePasse!2026',
            'role': 'candidat',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.authenticate(response.data['token'])

        profile = self.client.patch('/api/profile/', {
            'address': 'Douala', 'diploma': 'Licence', 'interests': ['droit'],
        }, format='json')
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data['user']['profile']['address'], 'Douala')

        avatar = self.client.post('/api/profile/avatar/', {
            'avatar': SimpleUploadedFile('portrait.png', b'\x89PNG\r\n\x1a\nprofile-image', content_type='image/png'),
        }, format='multipart')
        self.assertEqual(avatar.status_code, 200)
        self.assertTrue(avatar.data['avatarUrl'].startswith('/api/profile/avatar/'))
        avatar_file = self.client.get(avatar.data['avatarUrl'])
        self.assertEqual(avatar_file.status_code, 200)
        avatar_file.close()

        enrollment = self.client.post('/api/enrollments/', {'concourseId': self.concours.id_code}, format='json')
        self.assertEqual(enrollment.status_code, 201)
        self.assertEqual(self.client.get('/api/enrollments/').data[0]['concourse'], self.concours.id)

        flashcard = self.client.post('/api/content/', {
            'kind': 'flashcard', 'title': 'Mes cartes', 'status': 'published',
            'isPrivate': False, 'data': {'cards': [{'question': 'Q', 'answer': 'R'}]},
        }, format='json')
        self.assertEqual(flashcard.status_code, 201)
        self.assertTrue(flashcard.data['is_private'])
        self.assertEqual(flashcard.data['status'], 'published')

        progress = self.client.post('/api/progress/', {
            'contentId': flashcard.data['id'], 'completed': True, 'score': 100,
            'progress': {'mastered': 1},
        }, format='json')
        self.assertEqual(progress.status_code, 200)
        self.assertTrue(progress.data['completed'])

        topic = self.client.post('/api/forum/', {
            'title': 'Question réelle', 'category': 'Méthode', 'content': 'Comment structurer mes révisions ?',
        }, format='json')
        self.assertEqual(topic.status_code, 201)
        self.assertEqual(topic.data['author_name'], 'Nouvelle Candidate')
        self.assertEqual(topic.data['author_avatar'], avatar.data['avatarUrl'])
        self.assertEqual(topic.data['author_role'], 'candidat')
        self.assertEqual(self.client.post(f"/api/forum/{topic.data['id']}/like/").data['likesCount'], 1)
        self.assertEqual(self.client.post(f"/api/forum/{topic.data['id']}/reply/", {'content': 'Merci.'}, format='json').status_code, 201)

        event = self.client.post('/api/calendar/', {
            'title': 'Révision personnelle', 'concourseName': self.concours.title,
            'eventType': 'revision', 'eventDate': '2026-08-20',
        }, format='json')
        self.assertEqual(event.status_code, 201)
        changed = self.client.patch(f"/api/calendar/{event.data['id']}/", {'completed': True}, format='json')
        self.assertTrue(changed.data['completed'])

        self.assertEqual(self.client.post('/api/leaderboard/', {'quizTitle': 'Droit', 'score': 8, 'total': 10}, format='json').status_code, 201)
        ranking = self.client.get('/api/leaderboard/')
        self.assertEqual(ranking.status_code, 200)
        self.assertTrue(ranking.data[0]['is_current_user'])
        self.assertEqual(ranking.data[0]['total_points'], 8)

    def test_active_study_time_is_persisted_without_counting_idle_gaps(self):
        user, token = self.create_user('timer@example.org', 'candidat')
        self.authenticate(token)
        started = self.client.post('/api/study-sessions/', {
            'sessionKey': 'browser-session-1', 'action': 'heartbeat', 'context': {'view': 'courses'},
        }, format='json')
        self.assertEqual(started.status_code, 201)

        session = StudySession.objects.get(user=user, session_key='browser-session-1')
        session.last_heartbeat = timezone.now() - timedelta(seconds=35)
        session.save(update_fields=['last_heartbeat'])
        pulse = self.client.post('/api/study-sessions/', {
            'sessionKey': 'browser-session-1', 'action': 'heartbeat', 'context': {'view': 'courses'},
        }, format='json')
        self.assertEqual(pulse.status_code, 200)
        self.assertGreaterEqual(pulse.data['sessionSeconds'], 34)

        session.refresh_from_db()
        session.last_heartbeat = timezone.now() - timedelta(minutes=5)
        session.save(update_fields=['last_heartbeat'])
        idle_pulse = self.client.post('/api/study-sessions/', {
            'sessionKey': 'browser-session-1', 'action': 'heartbeat',
        }, format='json')
        self.assertEqual(idle_pulse.data['sessionSeconds'], pulse.data['sessionSeconds'])
        self.assertGreater(self.client.get('/api/activities/summary/').data['studyHours'], 0)

    def test_teacher_moderation_and_role_boundaries(self):
        candidate, candidate_token = self.create_user('candidate2@example.org', 'candidat')
        teacher, teacher_token = self.create_user('teacher@example.org', 'enseignant')
        admin, admin_token = self.create_user('admin@example.org', 'admin')

        self.authenticate(candidate_token)
        denied = self.client.post('/api/concours/', {
            'title': 'Interdit', 'category': 'Test', 'sourceName': 'Source', 'sourceUrl': 'https://example.org',
        }, format='json')
        self.assertEqual(denied.status_code, 403)

        self.authenticate(teacher_token)
        content = self.client.post('/api/content/', {
            'kind': 'course', 'title': 'Cours soumis', 'status': 'published',
            'data': {'chapters': []}, 'sourceName': 'Référence', 'sourceUrl': 'https://example.org/reference',
        }, format='json')
        self.assertEqual(content.status_code, 201)
        self.assertEqual(content.data['status'], 'draft')
        submission = self.client.post('/api/submissions/', {
            'title': 'Cours soumis', 'type': 'course', 'body': '{"chapters": []}',
        }, format='json')
        self.assertEqual(submission.status_code, 201)

        self.authenticate(admin_token)
        User.objects.create_user(username='legacy@example.org', email='legacy@example.org', password='MotDePasse!2026')
        overview = self.client.get('/api/admin/overview/')
        self.assertEqual(overview.status_code, 200)
        self.assertTrue(any(item['email'] == 'legacy@example.org' for item in overview.data['recentUsers']))
        moderation = self.client.patch(f"/api/submissions/{submission.data['id']}/moderate/", {'status': 'approved'}, format='json')
        self.assertEqual(moderation.status_code, 200)
        self.assertEqual(LearningContent.objects.get(pk=content.data['id']).status, 'published')

        public_contents = self.client.get('/api/content/?kind=course')
        self.assertEqual(public_contents.status_code, 200)
        self.assertEqual(public_contents.data[0]['title'], 'Cours soumis')

        self.authenticate(candidate_token)
        appointment = self.client.post('/api/appointments/', {
            'tutorId': teacher.id,
            'scheduledAt': (timezone.now() + timedelta(days=2)).isoformat(),
            'topic': 'Correction de dissertation',
        }, format='json')
        self.assertEqual(appointment.status_code, 201)
        self.assertEqual(appointment.data['status'], 'pending')
        self.assertEqual(appointment.data['candidate_name'], 'Candidat')
        self.assertEqual(appointment.data['candidate_email'], candidate.email)
        self.assertEqual(self.client.patch('/api/appointments/', {'id': appointment.data['id'], 'status': 'confirmed'}, format='json').status_code, 403)
        rejected_appointment = self.client.post('/api/appointments/', {
            'tutorId': teacher.id,
            'scheduledAt': (timezone.now() + timedelta(days=3)).isoformat(),
            'topic': 'Disponibilité alternative',
        }, format='json')
        self.assertEqual(rejected_appointment.status_code, 201)

        work = self.client.post('/api/work-submissions/', {
            'title': 'Copie de droit', 'question': 'Expliquez la légalité administrative.',
            'answer': 'La légalité administrative impose le respect des normes. En conclusion, elle encadre les décisions.',
            'teacherId': teacher.id, 'concourseId': self.concours.id_code,
        }, format='json')
        self.assertEqual(work.status_code, 201)
        self.assertEqual(work.data['local_evaluation']['engine'], 'local-rubric-v2-strict')

        recorded_exam = self.client.post('/api/activities/', {
            'activityType': 'exam', 'title': 'Examen blanc composite',
            'concourseId': self.concours.id_code, 'score': 11.5, 'total': 20,
            'details': {'complete': True, 'epreuveResults': [{'note': 11.5}]},
        }, format='json')
        self.assertEqual(recorded_exam.status_code, 201)
        composite_work = self.client.post('/api/work-submissions/', {
            'title': 'Examen blanc composite — copie complète',
            'question': 'Épreuves regroupées de l’examen blanc.',
            'answer': 'Une réponse complète suffisamment longue pour transmettre la copie enregistrée.',
            'concourseId': self.concours.id_code, 'activityId': recorded_exam.data['id'],
        }, format='json')
        self.assertEqual(composite_work.status_code, 201)
        self.assertEqual(composite_work.data['local_evaluation']['score'], 11.5)
        self.assertEqual(composite_work.data['local_evaluation']['engine'], 'recorded-exam-composite-v1')

        self.authenticate(teacher_token)
        teacher_notifications = self.client.get('/api/notifications/').data
        self.assertTrue(any(item['action_url'] == '/teacher/grading' and 'rendez-vous' in item['title'].lower() for item in teacher_notifications))
        confirmed = self.client.patch('/api/appointments/', {'id': appointment.data['id'], 'status': 'confirmed'}, format='json')
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.data['status'], 'confirmed')
        rejected = self.client.patch('/api/appointments/', {'id': rejected_appointment.data['id'], 'status': 'rejected'}, format='json')
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.data['status'], 'rejected')
        self.assertEqual(len(self.client.get('/api/work-submissions/').data), 1)
        reviewed = self.client.patch('/api/work-submissions/', {
            'id': work.data['id'], 'teacherScore': 14, 'teacherFeedback': 'Bonne base, développez davantage l’exemple.'
        }, format='json')
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.data['status'], 'reviewed')

        self.authenticate(candidate_token)
        candidate_notifications = self.client.get('/api/notifications/').data
        self.assertTrue(any(item['action_url'] == '/tutors' and 'confirmé' in item['title'].lower() for item in candidate_notifications))
        self.assertTrue(any(item['action_url'] == '/tutors' and 'refusé' in item['title'].lower() for item in candidate_notifications))
        self.assertTrue(any(item['action_url'] == '/past-papers' and 'corrigée' in item['title'].lower() for item in candidate_notifications))

    @patch('api.ai_services.GEMINI_API_KEY', '')
    @patch.dict('os.environ', {}, clear=False)
    def test_local_formative_evaluation_and_real_payment_boundary(self):
        candidate, token = self.create_user('candidate3@example.org', 'candidat')
        self.authenticate(token)

        ai = self.client.post('/api/gemini/grade-answer/', {
            'question': 'Expliquez le principe de légalité.',
            'candidateAnswer': 'Introduction. Le principe de légalité impose à l’administration de respecter le droit. En conclusion, il encadre son action.',
            'rubric': 'Définir le principe de légalité et expliquer le respect des normes.',
        }, format='json')
        self.assertEqual(ai.status_code, 200)
        self.assertEqual(ai.data['engine'], 'local-rubric-v2-strict')
        self.assertIn('breakdown', ai.data)
        self.assertTrue(ai.data['evaluationToken'])

        signed_copy = self.client.post('/api/work-submissions/', {
            'title': 'Copie avec note signée',
            'question': 'Expliquez le principe de légalité.',
            'answer': 'Introduction. Le principe de légalité impose à l’administration de respecter le droit. En conclusion, il encadre son action.',
            'rubric': 'Définir le principe de légalité et expliquer le respect des normes.',
            'concourseId': self.concours.id_code, 'evaluationMode': 'written',
            'evaluationToken': ai.data['evaluationToken'],
        }, format='json')
        self.assertEqual(signed_copy.status_code, 201)
        self.assertEqual(signed_copy.data['local_evaluation']['score'], ai.data['score'])
        self.assertEqual(signed_copy.data['local_evaluation']['detailedFeedback'], ai.data['detailedFeedback'])

        altered_copy = self.client.post('/api/work-submissions/', {
            'title': 'Copie modifiée', 'question': 'Expliquez le principe de légalité.',
            'answer': 'Cette réponse a été modifiée après la correction et ne correspond plus au jeton signé.',
            'rubric': 'Définir le principe de légalité et expliquer le respect des normes.',
            'evaluationMode': 'written', 'evaluationToken': ai.data['evaluationToken'],
        }, format='json')
        self.assertEqual(altered_copy.status_code, 400)

        for non_answer in ['', 'Je ne sais pas.', 'Bonjour, la cuisine et le football sont mes loisirs favoris chaque semaine.']:
            strict = self.client.post('/api/gemini/grade-answer/', {
                'question': 'Expliquez le principe de légalité administrative.',
                'candidateAnswer': non_answer,
                'rubric': 'Définition de la légalité, hiérarchie des normes et contrôle du juge.',
            }, format='json')
            self.assertEqual(strict.status_code, 200)
            self.assertEqual(strict.data['score'], 0)
            self.assertTrue(strict.data['eliminatory'])

        code = self.client.post('/api/gemini/grade-answer/', {
            'question': 'Écrire une fonction qui retourne la somme.',
            'candidateAnswer': 'def somme(valeurs):\n    return sum(valeurs)',
            'rubric': 'fonction somme valeurs return', 'evaluationMode': 'code', 'language': 'python',
        }, format='json')
        self.assertEqual(code.status_code, 200)
        self.assertEqual(code.data['engine'], 'local-code-rubric-v2-strict')
        self.assertTrue(code.data['syntaxValid'])

        empty_code = self.client.post('/api/gemini/grade-answer/', {
            'question': 'Écrire une fonction qui retourne la somme.',
            'candidateAnswer': '', 'rubric': 'fonction somme valeurs return',
            'evaluationMode': 'code', 'language': 'python',
        }, format='json')
        self.assertEqual(empty_code.data['score'], 0)
        self.assertTrue(empty_code.data['eliminatory'])

        oral = self.client.post('/api/gemini/jury-eval/', {
            'concourse': self.concours.title, 'question': 'Pourquoi servir le public ?',
            'transcript': 'D’abord, je souhaite servir le public. Ensuite, mon expérience m’a appris à organiser les priorités.',
            'duration': '01:10',
        }, format='json')
        self.assertEqual(oral.status_code, 200)
        self.assertEqual(oral.data['engine'], 'local-transcript-v2-strict')
        self.assertFalse(oral.data['postureMeasured'])

        empty_oral = self.client.post('/api/gemini/jury-eval/', {
            'concourse': self.concours.title, 'question': 'Pourquoi servir le public ?',
            'transcript': '', 'duration': '00:00',
        }, format='json')
        self.assertEqual(empty_oral.status_code, 200)
        self.assertEqual(empty_oral.data['clarityScore'], 0)
        self.assertEqual(empty_oral.data['relevanceScore'], 0)
        self.assertEqual(empty_oral.data['structureScore'], 0)
        self.assertTrue(empty_oral.data['eliminatory'])

        plan = LearningContent.objects.create(
            kind='subscription_plan', slug='paid-plan', title='Formule payante',
            status='published', data={'priceAmount': 1000},
        )
        with patch.dict('os.environ', {'PAYMENT_CHECKOUT_URL': ''}):
            payment = self.client.post('/api/subscriptions/', {'planId': plan.id, 'paymentMethod': 'external'}, format='json')
        self.assertEqual(payment.status_code, 503)
        self.assertIn('Aucun débit', payment.data['error'])

        free_plan = LearningContent.objects.create(
            kind='subscription_plan', slug='free-plan-test', title='Découverte test',
            status='published', data={'name': 'Découverte test', 'price': '0 FCFA', 'priceAmount': 0, 'period': 'sans limite'},
        )
        activated = self.client.post('/api/subscriptions/', {'planId': free_plan.id}, format='json')
        self.assertEqual(activated.status_code, 201)
        self.assertEqual(activated.data['status'], 'active')
        self.assertEqual(self.client.get('/api/subscriptions/').data[0]['plan_title'], 'Découverte test')
        self.assertTrue(any(item['action_url'] == '/pricing' for item in self.client.get('/api/notifications/').data))


class PopulatedPlatformTests(TestCase):
    @patch.dict('os.environ', {'POPULATE_DEFAULT_PASSWORD': '1234'})
    @patch('api.ai_services.GEMINI_API_KEY', '')
    def test_population_is_idempotent_and_grounded_modules_work(self):
        call_command('populate_platform', verbosity=0)
        first_count = LearningContent.objects.count()
        call_command('populate_platform', verbosity=0)
        self.assertEqual(LearningContent.objects.count(), first_count)

        tekeng = User.objects.get(email='tekeng@gmail.com')
        self.assertTrue(tekeng.check_password('1234'))
        self.assertEqual(tekeng.enrollments.count(), 2)
        self.assertEqual(UserProfile.objects.filter(role='enseignant').count(), 3)
        iai = Concours.objects.get(id_code='iai-cameroun-2026-travaux')
        self.assertEqual(iai.exam_date.isoformat(), '2026-07-31')
        self.assertEqual(iai.registration_deadline.isoformat(), '2026-07-28')
        self.assertIn('Génie logiciel', iai.description)
        self.assertGreaterEqual(LearningContent.objects.filter(concourse=iai, kind='course', status='published').count(), 6)
        self.assertGreaterEqual(LearningContent.objects.filter(concourse=iai, kind='quiz_bank', status='published').count(), 3)
        self.assertGreaterEqual(LearningContent.objects.filter(concourse=iai, kind='exam', status='published').count(), 3)
        self.assertGreaterEqual(LearningContent.objects.filter(concourse=iai, kind='checkpoint', status='published').count(), 8)
        for kind in ['course', 'quiz_bank', 'exam', 'flashcard', 'checkpoint', 'oral_bank', 'subscription_plan']:
            self.assertTrue(LearningContent.objects.filter(kind=kind, status='published').exists())
        for concours in Concours.objects.filter(active=True):
            for kind in ['course', 'quiz_bank', 'exam', 'checkpoint', 'oral_bank']:
                self.assertTrue(LearningContent.objects.filter(concourse=concours, kind=kind, status='published').exists(), f'{kind} absent pour {concours.id_code}')
            exam_data = LearningContent.objects.filter(concourse=concours, kind='exam', status='published').first().data
            self.assertGreaterEqual(len(exam_data['epreuves']), 2)
            self.assertTrue(all(epreuve.get('instructions') and epreuve.get('sections') for epreuve in exam_data['epreuves']))
        enam_exam = LearningContent.objects.get(slug='exam-auto-enam-2026-admin-a').data
        self.assertTrue(enam_exam['officialStructure'])
        self.assertEqual([item['coefficient'] for item in enam_exam['epreuves']], [4, 3, 2, 5])
        iut_exam = LearningContent.objects.get(slug='exam-auto-iut-ngaoundere-2026').data
        self.assertIn('code', [item['type'] for item in iut_exam['epreuves']])

        token = ApiToken.issue(tekeng)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.key}')
        document = (
            "Le service public répond à une mission d'intérêt général. "
            "Le principe de légalité impose à l'administration de respecter les normes applicables. "
            "La décentralisation transfère certaines compétences vers des collectivités autonomes. "
            "Le budget public prévoit et autorise les recettes et les dépenses publiques."
        )
        quiz = client.post('/api/gemini/generate-quiz/', {
            'documentText': document, 'documentTitle': 'Révision', 'questionCount': 3,
        }, format='json')
        self.assertEqual(quiz.status_code, 200)
        self.assertEqual(quiz.data['engine'], 'local-grounded')
        self.assertGreaterEqual(len(quiz.data['questions']), 1)

        orientation = client.post('/api/gemini/orientation-chat/', {
            'diploma': 'Licence', 'interest': 'administration droit public',
        }, format='json')
        self.assertEqual(orientation.status_code, 200)
        self.assertEqual(orientation.data['engine'], 'local-catalog-evidence-v2')
        self.assertGreaterEqual(len(orientation.data['recommendations']), 1)

        chat = client.post('/api/gemini/tutor-chat/', {
            'message': 'Quels contenus de droit public sont disponibles ?',
        }, format='json')
        self.assertEqual(chat.status_code, 200)
        self.assertEqual(chat.data['engine'], 'local-catalog-assistant-v2')
        self.assertIn('droit public', chat.data['reply'].lower())

        catalog_chat = client.post('/api/gemini/tutor-chat/', {
            'message': 'Quels concours sont disponibles sur la plateforme ?',
        }, format='json')
        self.assertEqual(catalog_chat.status_code, 200)
        self.assertEqual(catalog_chat.data['engine'], 'local-catalog-assistant-v2')
        self.assertIn('concours actifs', catalog_chat.data['reply'].lower())
        self.assertIn('ENAM', catalog_chat.data['reply'])
        self.assertIn('IUT', catalog_chat.data['reply'])

        appointment_chat = client.post('/api/gemini/tutor-chat/', {
            'message': 'Comment demander un rendez-vous avec un professeur ?',
        }, format='json')
        self.assertEqual(appointment_chat.status_code, 200)
        self.assertIn('rendez-vous', appointment_chat.data['reply'].lower())

        learning_chat = client.post('/api/gemini/tutor-chat/', {
            'message': 'Explique-moi ce qu’est un algorithme avec un exemple.',
        }, format='json')
        self.assertEqual(learning_chat.status_code, 200)
        self.assertEqual(learning_chat.data['engine'], 'local-learning-assistant-v3')
        self.assertIn('suite finie', learning_chat.data['reply'].lower())
