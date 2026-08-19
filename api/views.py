import json
import uuid
import os
import django
import base64
import io
import re
import unicodedata
import mimetypes
import hashlib
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth.models import User
from django.db.models import Avg, Sum, Max, Q, Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db import transaction
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import FileResponse
from django.core import signing
from .models import (
    UserProfile, Concours, Resource, Submission, Quiz,
    QuizAttempt, ForumTopic, ForumReply, ForumLike, CalendarEvent, OralSession,
    ApiToken, Enrollment, LearningContent, UserProgress, Activity,
    Notification, TutorMessage, TutorAppointment, Subscription, CandidateWorkSubmission, StudySession
)
from .serializers import (
    UserSerializer, ConcoursSerializer, ResourceSerializer, SubmissionSerializer,
    QuizSerializer, QuizAttemptSerializer, ForumTopicSerializer, ForumReplySerializer,
    CalendarEventSerializer, OralSessionSerializer, EnrollmentSerializer,
    LearningContentSerializer, UserProgressSerializer, ActivitySerializer,
    NotificationSerializer, TutorMessageSerializer, TutorAppointmentSerializer,
    SubscriptionSerializer, CandidateWorkSubmissionSerializer
)
from .ai_services import evaluate_oral_jury, tutor_chat_reply, generate_quiz_from_text, generate_material_from_text, orientation_advisor, grade_open_answer, local_code_grade


def request_user(request):
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    key = auth_header[7:].strip()
    token = ApiToken.objects.select_related('user').filter(key=key).first()
    if not token:
        return None
    if not hasattr(token.user, 'profile') or token.user.profile.status != 'active':
        return None
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return token.user


def auth_error():
    return Response({'error': 'Authentification requise.'}, status=status.HTTP_401_UNAUTHORIZED)


def role_error():
    return Response({'error': 'Permission insuffisante.'}, status=status.HTTP_403_FORBIDDEN)


def has_role(user, *roles):
    return user and hasattr(user, 'profile') and user.profile.role in roles


def concours_from_value(value):
    if not value:
        return None
    query = Q(id_code=str(value))
    if str(value).isdigit():
        query |= Q(pk=int(value))
    return Concours.objects.filter(query).first()


def search_tokens(value):
    plain = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii').lower()
    ignored = {'avec', 'dans', 'pour', 'sans', 'quelle', 'quelles', 'quels', 'comment', 'faire', 'avoir', 'etre', 'cela', 'cette', 'tout', 'tous'}
    return {token for token in re.findall(r"[a-z0-9'-]{3,}", plain) if token not in ignored}


def plain_text(value):
    return unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii').lower()


def evaluation_fingerprint(question, answer, rubric='', mode='written', language=''):
    payload = json.dumps({
        'question': str(question or '').strip(), 'answer': str(answer or '').strip(),
        'rubric': str(rubric or '').strip(), 'mode': str(mode or 'written'),
        'language': str(language or '').lower(),
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def grounded_learning_reply(message, contents):
    """Répond aux questions pédagogiques fréquentes à partir de notions stables et du contenu publié."""
    query = plain_text(message)
    tokens = search_tokens(message)
    learning_intent = any(signal in query for signal in [
        "qu'est-ce", 'quest ce', 'explique', 'expliquer', 'definition', 'definir',
        'difference entre', 'comment fonctionne', 'a quoi sert', 'donne un exemple', 'pourquoi',
    ])
    if not learning_intent:
        return None

    concepts = [
        ({'algorithme', 'algorithmique'}, "Un algorithme est une suite finie et ordonnée d’étapes qui transforme des données d’entrée en un résultat. Pour l’analyser, précisez les entrées, les traitements, les sorties, les cas limites et le coût en temps et en mémoire. Exemple : pour chercher le maximum d’une liste, on parcourt les valeurs en conservant la plus grande rencontrée."),
        ({'fonction', 'procedure'}, "En programmation, une fonction regroupe un traitement réutilisable. Elle reçoit éventuellement des paramètres, exécute des instructions et retourne un résultat. Une procédure réalise surtout une action ; selon le langage, elle peut ne retourner aucune valeur."),
        ({'boucle', 'iteration'}, "Une boucle répète un bloc d’instructions. Utilisez une boucle « for » lorsque le nombre d’itérations ou la collection est connu, et une boucle « while » lorsque la répétition dépend d’une condition. Vérifiez toujours la condition d’arrêt pour éviter une boucle infinie."),
        ({'base', 'donnees', 'sql'}, "Une base de données organise des informations persistantes. Dans une base relationnelle, les données sont réparties en tables reliées par des clés. SQL permet notamment de lire avec SELECT, d’ajouter avec INSERT, de modifier avec UPDATE et de supprimer avec DELETE ; les contraintes protègent la cohérence."),
        ({'reseau', 'ip', 'tcp'}, "Une adresse IP identifie une interface sur un réseau. IP assure l’acheminement des paquets ; TCP ajoute une transmission ordonnée et fiable, tandis qu’UDP privilégie la rapidité sans garantie équivalente. Un masque de sous-réseau sépare la partie réseau de la partie hôte."),
        ({'osi'}, "Le modèle OSI décrit les communications réseau en sept couches : physique, liaison, réseau, transport, session, présentation et application. Il sert surtout à localiser les responsabilités et à diagnostiquer une panne, de la transmission du signal jusqu’au service utilisé."),
        ({'cybersecurite', 'securite'}, "La cybersécurité protège la confidentialité, l’intégrité et la disponibilité des systèmes. Une réponse solide distingue menace, vulnérabilité et risque, puis combine prévention, détection, réaction et sauvegarde. Aucun contrôle isolé ne suffit."),
        ({'matrice', 'matrices'}, "Une matrice est un tableau de nombres organisé en lignes et colonnes. L’addition exige les mêmes dimensions ; le produit AB est défini lorsque le nombre de colonnes de A égale le nombre de lignes de B. Les matrices représentent notamment des systèmes linéaires et des transformations."),
        ({'derivee', 'derivation'}, "La dérivée mesure le taux de variation instantané d’une fonction. Géométriquement, elle donne la pente de la tangente. Pour étudier une fonction, déterminez son domaine, calculez la dérivée, étudiez son signe puis déduisez les variations et les extremums."),
        ({'probabilite', 'probabilites'}, "Une probabilité mesure la vraisemblance d’un événement entre 0 et 1. Sur un univers fini équiprobable, P(A) est le nombre de cas favorables divisé par le nombre de cas possibles. Pour des événements indépendants, P(A∩B)=P(A)P(B)."),
        ({'legalite'}, "Le principe de légalité impose à l’administration de respecter les normes qui lui sont supérieures : Constitution, engagements applicables, lois et règlements. Une décision illégale peut être contestée devant l’autorité compétente ou le juge selon les procédures prévues."),
        ({'service', 'public'}, "Un service public est une activité d’intérêt général prise en charge ou contrôlée par une personne publique. Son fonctionnement est classiquement guidé par la continuité, l’égalité des usagers et l’adaptation aux besoins collectifs."),
        ({'inflation'}, "L’inflation est une hausse générale et durable du niveau des prix. Elle réduit le pouvoir d’achat si les revenus progressent moins vite. Elle peut provenir des coûts, de la demande ou de facteurs monétaires et appelle une analyse de ses causes avant toute politique de réponse."),
        ({'evaluation', 'formative'}, "L’évaluation formative intervient pendant l’apprentissage : elle identifie les acquis et les difficultés afin d’adapter le travail. Elle repose sur des critères explicites, une rétroaction précise et une remédiation, contrairement à une simple note finale."),
    ]
    best_concept = None
    best_score = 0
    for keywords, explanation in concepts:
        score = len(tokens.intersection(keywords))
        if score > best_score:
            best_score, best_concept = score, explanation
    if best_concept:
        return {'reply': best_concept + "\n\nSi vous le souhaitez, je peux maintenant proposer un exercice de niveau concours ou corriger votre propre explication.", 'engine': 'local-learning-assistant-v3'}

    matches = []
    for content in contents:
        if content.kind != 'quiz_bank':
            continue
        for question in content.data.get('questions', []):
            corpus = plain_text(f"{question.get('question', '')} {question.get('explanation', '')}")
            score = sum(1 for token in tokens if token in corpus)
            if score:
                matches.append((score, question, content))
    matches.sort(key=lambda row: -row[0])
    threshold = 1 if len(tokens) <= 2 else 2
    if matches and matches[0][0] >= threshold:
        _, question, content = matches[0]
        answer = question.get('explanation') or 'Consultez le corrigé associé à cette question.'
        return {
            'reply': f"{answer}\n\nRepère utilisé : {content.title} — {content.concourse.title if content.concourse else 'plateforme'}.",
            'engine': 'local-learning-assistant-v3',
        }
    return None


def grounded_catalog_reply(message):
    query = plain_text(message)
    tokens = search_tokens(message)
    concours_list = list(Concours.objects.filter(active=True).order_by('title'))
    contents = list(LearningContent.objects.filter(status='published', is_private=False).select_related('concourse'))

    if query.strip() in {'bonjour', 'bonsoir', 'salut', 'hello', 'hey'}:
        return {'reply': f"Bonjour ! Je peux répondre sur les {len(concours_list)} concours publiés, leurs matières, cours, dates, conditions, examens, professeurs, rendez-vous et abonnements. Posez votre question librement.", 'engine': 'local-catalog-assistant-v2'}

    if any(term in query for term in ['tous les concours', 'liste des concours', 'quels concours', 'concours disponibles', 'catalogue complet']):
        lines = [f"• {item.title} — {item.category} ({item.session})" for item in concours_list]
        return {'reply': f"La plateforme contient {len(concours_list)} concours actifs :\n" + '\n'.join(lines), 'engine': 'local-catalog-assistant-v2'}

    if any(term in query for term in ['abonnement', 'formule', 'tarif', 'prix', 'premium']):
        plans = [item for item in contents if item.kind == 'subscription_plan']
        lines = [f"• {plan.data.get('name', plan.title)} : {plan.data.get('price', 'tarif non renseigné')} — {', '.join(plan.data.get('features', []))}" for plan in plans]
        return {'reply': "Voici les formules publiées :\n" + ('\n'.join(lines) or 'Aucune formule publiée.') + "\nVous pouvez changer de formule dans « Offres & Abonnements ».", 'engine': 'local-catalog-assistant-v2'}

    platform_answers = [
        (['rendez-vous', 'rendez vous', 'rdv'], "Ouvrez « Professeurs & messagerie », choisissez un enseignant puis demandez un rendez-vous. Le professeur peut confirmer ou refuser ; vous recevez sa décision dans les notifications."),
        (['copie', 'correction', 'corriger', 'note', 'jury'], "Après une composition, vous pouvez demander une note formative stricte ou transmettre toute la copie à un professeur. Sa note sur 20 et son appréciation apparaissent dans « Annales & Copies » et une notification vous y conduit."),
        (['forum', 'entraide', 'discussion'], "Le forum conserve le nom, le rôle et l’avatar du compte authentifié. Une réponse à votre discussion déclenche une notification."),
        (['planning', 'calendrier', 'programme de revision'], "Le planning permet de programmer une révision, un quiz, un oral ou un examen, puis de marquer l’objectif comme terminé. Le temps actif est comptabilisé séparément."),
        (['professeur', 'enseignant', 'tuteur', 'message'], "Dans « Professeurs & messagerie », vous pouvez consulter la spécialité de chaque enseignant, lui écrire et demander un rendez-vous."),
    ]
    for signals, answer in platform_answers:
        if any(signal in query for signal in signals):
            return {'reply': answer, 'engine': 'local-catalog-assistant-v2'}

    method_answers = [
        (['dissertation', 'composition'], "Méthode conseillée : analysez les termes du sujet, formulez une problématique, construisez un plan qui répond exactement à cette problématique, puis développez chaque argument avec définition, justification et exemple. Terminez par une conclusion qui répond au problème posé."),
        (['oral', 'parler', 'presentation'], "Pour l’oral : répondez d’abord directement, annoncez deux ou trois idées, justifiez-les avec un exemple concret puis concluez. Utilisez la transcription pour vérifier la clarté et la structure avant de demander l’évaluation."),
        (['memoriser', 'apprendre', 'reviser', 'revision'], "Pour réviser efficacement : alternez lecture active, rappel sans support, flashcards et exercices. Planifiez des reprises espacées, analysez chaque erreur et validez le checkpoint lié au cours avant de passer à la matière suivante."),
    ]
    for signals, answer in method_answers:
        if any(signal in query for signal in signals):
            return {'reply': answer, 'engine': 'local-catalog-assistant-v2'}

    learning_reply = grounded_learning_reply(message, contents)
    if learning_reply:
        return learning_reply

    ranked_contests = []
    for concours in concours_list:
        corpus = plain_text(' '.join([concours.title, concours.category, concours.description or '', *concours.subjects, *concours.requirements, *concours.career_paths]))
        score = sum(1 for token in tokens if token in corpus)
        if plain_text(concours.title) in query:
            score += 5
        ranked_contests.append((score, concours))
    ranked_contests.sort(key=lambda row: (-row[0], row[1].title))

    ranked_contents = []
    for content in contents:
        corpus = plain_text(f"{content.title} {content.kind} {content.concourse.title if content.concourse else ''} {json.dumps(content.data, ensure_ascii=False)}")
        score = sum(1 for token in tokens if token in corpus)
        ranked_contents.append((score, content))
    ranked_contents.sort(key=lambda row: (-row[0], row[1].title))
    relevant_contests = [item for score, item in ranked_contests if score > 0][:4]
    relevant_contents = [item for score, item in ranked_contents if score > 0][:5]

    if relevant_contests:
        lines = []
        for item in relevant_contests:
            details = [f"matières : {', '.join(item.subjects) or 'non renseignées'}"]
            if item.exam_date:
                details.append(f"épreuves : {item.exam_date.strftime('%d/%m/%Y')}")
            if item.registration_deadline:
                details.append(f"fin des inscriptions : {item.registration_deadline.strftime('%d/%m/%Y')}")
            if item.requirements:
                details.append(f"conditions : {', '.join(item.requirements[:4])}")
            if item.career_paths:
                details.append(f"débouchés : {', '.join(item.career_paths[:4])}")
            if item.source_url:
                details.append(f"source : {item.source_url}")
            lines.append(f"• {item.title}\n  " + ' ; '.join(details))
        if relevant_contents:
            lines.append("Contenus associés : " + ', '.join(item.title for item in relevant_contents))
        return {'reply': "Voici les informations correspondantes dans tout le catalogue :\n" + '\n'.join(lines), 'engine': 'local-catalog-assistant-v2'}

    if relevant_contents:
        lines = [f"• {item.title} — {item.concourse.title if item.concourse else 'plateforme'}" for item in relevant_contents]
        return {'reply': "Contenus publiés correspondant à votre question :\n" + '\n'.join(lines), 'engine': 'local-catalog-assistant-v2'}

    categories = ', '.join(sorted({item.category for item in concours_list}))
    return {
        'reply': "Je n’ai pas trouvé de donnée publiée permettant une réponse factuelle sans invention. "
                 f"Je peux chercher dans tout le catalogue ({categories}) ou vous aider sur la méthodologie, les copies, le forum, les rendez-vous et les abonnements. Précisez le sujet ou la matière.",
        'engine': 'local-catalog-no-match',
    }


def grounded_orientation(diploma, interest, experience=''):
    profile_text = unicodedata.normalize('NFKD', f'{diploma} {interest} {experience}').encode('ascii', 'ignore').decode('ascii').lower()
    tokens = search_tokens(profile_text)
    # Vocabulaire métier explicite : il sert uniquement à retrouver des fiches du catalogue.
    domains = {
        'droit et justice': {'droit', 'justice', 'juriste', 'magistrat', 'greffe', 'tribunal', 'avocat'},
        'administration publique': {'administration', 'public', 'etat', 'gouvernance', 'fonctionnaire', 'enam'},
        'finances publiques': {'finance', 'finances', 'economie', 'comptabilite', 'impot', 'tresor', 'douane'},
        'enseignement': {'enseignement', 'enseignant', 'professeur', 'pedagogie', 'education', 'ens', 'enset'},
        'informatique': {'informatique', 'numerique', 'cyber', 'cybersecurite', 'logiciel', 'reseau', 'programmation', 'ia'},
        'sante': {'sante', 'medecine', 'medical', 'infirmier', 'pharmacie', 'biologie'},
        'ingenierie': {'ingenieur', 'ingenierie', 'polytechnique', 'industrie', 'electrique', 'mecanique'},
        'defense et securite': {'armee', 'militaire', 'defense', 'securite', 'commandement', 'emia', 'police'},
        'sport et jeunesse': {'sport', 'jeunesse', 'animation', 'injs', 'education physique'},
    }
    profile_domains = {name for name, vocabulary in domains.items() if any(term in profile_text for term in vocabulary)}
    ranked = []
    for concours in Concours.objects.filter(active=True):
        corpus = unicodedata.normalize('NFKD', ' '.join([
            concours.title, concours.category, concours.description or '',
            *concours.subjects, *concours.requirements, *concours.career_paths,
        ])).encode('ascii', 'ignore').decode('ascii').lower()
        matches = sorted(token for token in tokens if token in corpus)
        concours_domains = {name for name, vocabulary in domains.items() if any(term in corpus for term in vocabulary)}
        matched_domains = sorted(profile_domains.intersection(concours_domains))
        score = len(matches) + 3 * len(matched_domains)
        ranked.append((score, concours, matches, matched_domains))
    ranked.sort(key=lambda row: (-row[0], row[1].title))
    recommendations = []
    for count, concours, matches, matched_domains in [row for row in ranked if row[0] > 0][:4]:
        evidence = []
        if matched_domains:
            evidence.append(f"domaines rapprochés : {', '.join(matched_domains)}")
        if matches:
            evidence.append(f"mots présents dans la fiche : {', '.join(matches[:8])}")
        denominator = max(3, len(tokens) + len(profile_domains) * 2)
        recommendations.append({
            'concourse': concours.title,
            'matchScore': min(95, round(100 * count / denominator)),
            'reason': ' ; '.join(evidence) + '.',
            'subjects': concours.subjects[:5],
            'requirements': concours.requirements[:5],
            'sourceUrl': concours.source_url,
            'sourceName': concours.source_name,
        })
    if not recommendations:
        return {
            'recommendations': [],
            'advice': "Votre projet est encore trop général pour proposer un concours sans vous induire en erreur. Précisez un métier ou un domaine (justice, enseignement, santé, informatique, administration, défense, sport ou ingénierie).",
            'engine': 'local-catalog-evidence-v2',
        }
    return {
        'recommendations': recommendations,
        'advice': "Ces rapprochements sont fondés sur les matières, débouchés et descriptions enregistrés. Ils ne valident ni le diplôme, ni l’âge, ni l’éligibilité : ouvrez la source officielle de chaque fiche avant de vous inscrire.",
        'engine': 'local-catalog-evidence-v2',
    }

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    return Response({'status': 'ok', 'backend': 'Django REST Framework', 'djangoVersion': django.get_version()})

# --- AUTHENTICATION VIEWS ---

@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    try:
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        user = User.objects.filter(email__iexact=email).first()
        if not user:
            user = User.objects.filter(username__iexact=email).first()

        if not user or not user.check_password(password):
            return Response({'error': 'Identifiants invalides.'}, status=status.HTTP_401_UNAUTHORIZED)

        profile, _ = UserProfile.objects.get_or_create(user=user)
        if user.is_superuser and profile.role != 'admin':
            profile.role = 'admin'
            profile.save(update_fields=['role'])
        if profile.status != 'active':
            return Response({'error': 'Ce compte est suspendu.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = UserSerializer(user)
        token = ApiToken.issue(user)
        return Response({'token': token.key, 'user': serializer.data})
    except Exception as e:
        return Response({'error': f"Erreur serveur: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([AllowAny])
def register_view(request):
    try:
        name = request.data.get('name', '').strip()
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')
        requested_role = request.data.get('role', 'candidat')
        role = requested_role if requested_role == 'candidat' else 'candidat'
        phone = request.data.get('phone', '')
        target_concours = request.data.get('targetConcours', '')

        if not email or not password or not name:
            return Response({'error': 'Veuillez remplir tous les champs requis.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_email(email)
        except ValidationError:
            return Response({'error': 'Adresse e-mail invalide.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(password) < 10:
            return Response({'error': 'Le mot de passe doit contenir au moins 10 caractères.'}, status=status.HTTP_400_BAD_REQUEST)

        if requested_role != 'candidat':
            return Response(
                {'error': 'Les comptes enseignant et administrateur doivent être créés par un administrateur.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if User.objects.filter(email__iexact=email).exists():
            return Response({'error': 'Cet email est déjà utilisé.'}, status=status.HTTP_400_BAD_REQUEST)

        username = email.split('@')[0] + "_" + uuid.uuid4().hex[:6]
        name_parts = name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        UserProfile.objects.create(
            user=user,
            role=role,
            status='active',
            phone=phone,
            target_concours=target_concours if role == 'candidat' else ''
        )

        token = ApiToken.issue(user)
        return Response({'token': token.key, 'user': UserSerializer(user).data}, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({'error': f"Erreur lors de la création du compte: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([AllowAny])
def me_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    return Response({'user': UserSerializer(user).data})


@api_view(['POST'])
@permission_classes([AllowAny])
def logout_view(request):
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        ApiToken.objects.filter(key=auth_header[7:].strip()).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([AllowAny])
def change_password_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    current_password = request.data.get('currentPassword', '')
    new_password = request.data.get('newPassword', '')
    if not user.check_password(current_password):
        return Response({'error': 'Le mot de passe actuel est incorrect.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(new_password) < 10:
        return Response({'error': 'Le nouveau mot de passe doit contenir au moins 10 caractères.'}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.save(update_fields=['password'])
    token = ApiToken.issue(user)
    return Response({'token': token.key})


@api_view(['GET', 'PATCH'])
@permission_classes([AllowAny])
def profile_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if request.method == 'PATCH':
        if 'name' in request.data:
            parts = str(request.data['name']).strip().split(' ', 1)
            user.first_name = parts[0] if parts else ''
            user.last_name = parts[1] if len(parts) > 1 else ''
        if 'email' in request.data:
            email = str(request.data['email']).strip().lower()
            try:
                validate_email(email)
            except ValidationError:
                return Response({'error': 'Adresse e-mail invalide.'}, status=status.HTTP_400_BAD_REQUEST)
            if User.objects.exclude(pk=user.pk).filter(email__iexact=email).exists():
                return Response({'error': 'Cet email est déjà utilisé.'}, status=status.HTTP_400_BAD_REQUEST)
            user.email = email
        user.save()
        field_map = {
            'phone': 'phone', 'targetConcours': 'target_concours', 'address': 'address',
            'diploma': 'diploma', 'university': 'university', 'specialty': 'specialty',
            'bio': 'bio', 'avatarUrl': 'avatar_url',
            'interests': 'interests',
            'emailNotifications': 'email_notifications', 'smsNotifications': 'sms_notifications',
            'pushNotifications': 'push_notifications',
        }
        for incoming, model_field in field_map.items():
            if incoming in request.data:
                setattr(profile, model_field, request.data[incoming])
        profile.save()
        user.refresh_from_db()
    return Response({'user': UserSerializer(user).data})


@api_view(['POST'])
@permission_classes([AllowAny])
def profile_avatar_upload(request):
    user = request_user(request)
    if not user:
        return auth_error()
    uploaded = request.FILES.get('avatar')
    if not uploaded:
        return Response({'error': 'Sélectionnez une image.'}, status=status.HTTP_400_BAD_REQUEST)
    if uploaded.size > 2 * 1024 * 1024:
        return Response({'error': 'La photo doit peser 2 Mo maximum.'}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    allowed = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}
    extension = allowed.get(str(uploaded.content_type).lower())
    content = uploaded.read()
    signatures_valid = (
        extension == 'jpg' and content.startswith(b'\xff\xd8\xff') or
        extension == 'png' and content.startswith(b'\x89PNG\r\n\x1a\n') or
        extension == 'webp' and content.startswith(b'RIFF') and content[8:12] == b'WEBP'
    )
    if not extension or not signatures_valid:
        return Response({'error': 'Format invalide. Utilisez une image JPEG, PNG ou WebP.'}, status=status.HTTP_400_BAD_REQUEST)
    profile, _ = UserProfile.objects.get_or_create(user=user)
    previous = str(profile.avatar_url or '')
    stored_path = default_storage.save(f'avatars/{user.id}-{uuid.uuid4().hex}.{extension}', ContentFile(content))
    profile.avatar_url = f'/api/profile/avatar/{os.path.basename(stored_path)}'
    profile.save(update_fields=['avatar_url'])
    if previous.startswith('/api/profile/avatar/'):
        previous_name = os.path.basename(previous)
        previous_path = f'avatars/{previous_name}'
        if previous_name and previous_path != stored_path and default_storage.exists(previous_path):
            default_storage.delete(previous_path)
    return Response({'avatarUrl': profile.avatar_url, 'user': UserSerializer(user).data})


@api_view(['GET'])
@permission_classes([AllowAny])
def profile_avatar_file(request, filename):
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name != filename:
        return Response({'error': 'Image introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    stored_path = f'avatars/{safe_name}'
    if not default_storage.exists(stored_path):
        return Response({'error': 'Image introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    content_type = mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'
    return FileResponse(default_storage.open(stored_path, 'rb'), content_type=content_type)

# --- CONCOURS CRUD VIEWS ---

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def concours_list_create(request):
    if request.method == 'GET':
        concours = Concours.objects.filter(active=True)
        serializer = ConcoursSerializer(concours, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        user = request_user(request)
        if not has_role(user, 'admin'):
            return role_error() if user else auth_error()
        title = request.data.get('title')
        category = request.data.get('category')
        session_year = request.data.get('session', '2026')
        modules = request.data.get('modules', [])
        source_url = request.data.get('sourceUrl', '').strip()
        source_name = request.data.get('sourceName', '').strip()

        if not title or not category or not source_url or not source_name:
            return Response({'error': 'Titre, catégorie et source officielle sont obligatoires.'}, status=status.HTTP_400_BAD_REQUEST)

        id_code = f"concours-{uuid.uuid4().hex[:6]}"
        c = Concours.objects.create(
            id_code=id_code,
            title=title,
            category=category,
            session=session_year,
            modules=modules,
            description=request.data.get('description', ''),
            requirements=request.data.get('requirements', []),
            subjects=request.data.get('subjects', modules),
            career_paths=request.data.get('careerPaths', []),
            exam_date=request.data.get('examDate') or None,
            registration_deadline=request.data.get('registrationDeadline') or None,
            source_name=source_name,
            source_url=source_url,
            verified_at=timezone.now(),
            active=True
        )
        return Response(ConcoursSerializer(c).data, status=status.HTTP_201_CREATED)

@api_view(['PATCH', 'DELETE'])
@permission_classes([AllowAny])
def concours_detail(request, pk):
    user = request_user(request)
    if not has_role(user, 'admin'):
        return role_error() if user else auth_error()
    try:
        c = Concours.objects.get(pk=pk)
    except Concours.DoesNotExist:
        return Response({'error': 'Concours non trouvé.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'PATCH':
        if ('source_url' in request.data and not request.data.get('source_url')) or ('source_name' in request.data and not request.data.get('source_name')):
            return Response({'error': 'Une fiche publiée doit conserver sa source.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ConcoursSerializer(c, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        c.active = False
        c.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

# --- RESOURCES VIEWS ---

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def resource_list_create(request):
    if request.method == 'GET':
        concourse_id = request.query_params.get('concourseId', None)
        qs = Resource.objects.filter(status='published')
        if concourse_id:
            query = Q(concourse__id_code=concourse_id)
            if str(concourse_id).isdigit():
                query |= Q(concourse__id=int(concourse_id))
            qs = qs.filter(query)
        serializer = ResourceSerializer(qs, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        user = request_user(request)
        if not user:
            user = User.objects.filter(profile__role='admin').first() or User.objects.first()

        title = request.data.get('title')
        res_type = request.data.get('type', 'pdf')
        file_name = request.data.get('fileName') or 'document.pdf'
        url = request.data.get('url', '').strip()
        concourse_name = request.data.get('concourseName', '')
        concourse_id = request.data.get('concourseId')
        
        concourse = concours_from_value(concourse_id) if concourse_id else None
        if not concourse and concourse_name:
            concourse = Concours.objects.filter(Q(title__icontains=concourse_name) | Q(id_code__iexact=concourse_name)).first()
        if concourse and not concourse_name:
            concourse_name = concourse.title

        if not title:
            return Response({'error': 'Le titre de la ressource est obligatoire.'}, status=status.HTTP_400_BAD_REQUEST)

        if not url:
            url = f"https://concours-cm.org/resources/{res_type}/{file_name}"

        meta = request.data.get('metadata', {})
        if not isinstance(meta, dict):
            meta = {}
        if request.data.get('subject'):
            meta['subject'] = request.data.get('subject')

        res = Resource.objects.create(
            title=title,
            type=res_type,
            file_name=file_name,
            url=url,
            concourse=concourse,
            concourse_name=concourse_name or (concourse.title if concourse else 'Général'),
            author=user,
            metadata=meta,
            status='published'
        )
        return Response(ResourceSerializer(res).data, status=status.HTTP_201_CREATED)

@api_view(['DELETE'])
@permission_classes([AllowAny])
def resource_detail(request, pk):
    user = request_user(request)
    if not has_role(user, 'enseignant', 'admin'):
        return role_error() if user else auth_error()
    resource = Resource.objects.filter(pk=pk).first()
    if not resource:
        return Response({'error': 'Ressource introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    if not has_role(user, 'admin') and resource.author_id != user.id:
        return role_error()
    resource.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)

# --- SUBMISSIONS & MODERATION ---

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def submission_list_create(request):
    if request.method == 'GET':
        auth_user = request_user(request)
        if not has_role(auth_user, 'enseignant', 'admin'):
            return role_error() if auth_user else auth_error()
        qs = Submission.objects.all() if has_role(auth_user, 'admin') else Submission.objects.filter(author=auth_user)
        qs = qs.order_by('-created_at')
        serializer = SubmissionSerializer(qs, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        auth_user = request_user(request)
        if not has_role(auth_user, 'enseignant', 'admin'):
            return role_error() if auth_user else auth_error()
        title = request.data.get('title')
        sub_type = request.data.get('type', 'annale')
        body = request.data.get('body', '')

        sub = Submission.objects.create(
            title=title,
            type=sub_type,
            body=body,
            author=auth_user,
            status='pending'
        )
        return Response(SubmissionSerializer(sub).data, status=status.HTTP_201_CREATED)

@api_view(['PATCH'])
@permission_classes([AllowAny])
def submission_moderate(request, pk):
    user = request_user(request)
    if not has_role(user, 'admin'):
        return role_error() if user else auth_error()
    try:
        sub = Submission.objects.get(pk=pk)
    except Submission.DoesNotExist:
        return Response({'error': 'Contenu introuvable.'}, status=status.HTTP_404_NOT_FOUND)

    new_status = request.data.get('status')
    if new_status in ['approved', 'rejected']:
        sub.status = new_status
        sub.save()
        if new_status == 'approved':
            LearningContent.objects.filter(author=sub.author, title=sub.title, status='draft').update(status='published', updated_at=timezone.now())
        else:
            LearningContent.objects.filter(author=sub.author, title=sub.title, status='draft').update(status='archived', updated_at=timezone.now())
        return Response(SubmissionSerializer(sub).data)
    return Response({'error': 'Statut de modération invalide.'}, status=status.HTTP_400_BAD_REQUEST)

# --- FORUM COMPARTMENT ---

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def forum_topics_list_create(request):
    if request.method == 'GET':
        topics = ForumTopic.objects.all().order_by('-is_pinned', '-created_at')
        return Response(ForumTopicSerializer(topics, many=True).data)

    elif request.method == 'POST':
        user = request_user(request)
        if not user:
            return auth_error()
        title = request.data.get('title')
        category = request.data.get('category', 'Général')
        content = request.data.get('content', '')
        topic = ForumTopic.objects.create(
            title=title,
            category=category,
            content=content,
            author=user
        )
        return Response(ForumTopicSerializer(topic).data, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@permission_classes([AllowAny])
def forum_reply_create(request, topic_pk):
    user = request_user(request)
    if not user:
        return auth_error()
    try:
        topic = ForumTopic.objects.get(pk=topic_pk)
    except ForumTopic.DoesNotExist:
        return Response({'error': 'Sujet non trouvé.'}, status=status.HTTP_404_NOT_FOUND)

    content = request.data.get('content')
    reply = ForumReply.objects.create(
        topic=topic,
        author=user,
        content=content
    )
    if topic.author_id != user.id:
        Notification.objects.create(
            user=topic.author, title='Nouvelle réponse dans le forum',
            message=f"{user.get_full_name() or user.username} a répondu à « {topic.title} ».",
            type='system', action_url='/forum',
        )
    return Response(ForumReplySerializer(reply).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def forum_like_toggle(request, topic_pk):
    user = request_user(request)
    if not user:
        return auth_error()
    topic = ForumTopic.objects.filter(pk=topic_pk).first()
    if not topic:
        return Response({'error': 'Sujet non trouvé.'}, status=status.HTTP_404_NOT_FOUND)
    like, created = ForumLike.objects.get_or_create(topic=topic, user=user)
    if not created:
        like.delete()
    return Response({'liked': created, 'likesCount': topic.likes.count()})

# --- LEADERBOARD & QUIZ ATTEMPTS COMPARTMENT ---

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def leaderboard_list_create_attempt(request):
    auth_user = request_user(request)
    if not auth_user:
        return auth_error()
    if request.method == 'GET':
        rows = list(
            QuizAttempt.objects.filter(user__profile__role='candidat', user__profile__status='active')
            .values('user_id', 'user__first_name', 'user__last_name', 'user__username')
            .annotate(
                quizzes_count=Count('id'),
                average_score=Avg('percentage'),
                total_points=Sum('score'),
            )
            .order_by('-total_points', '-average_score', 'user_id')[:100]
        )
        payload = []
        for rank, row in enumerate(rows, start=1):
            full_name = f"{row['user__first_name']} {row['user__last_name']}".strip()
            payload.append({
                'user': row['user_id'],
                'user_name': full_name or row['user__username'],
                'rank': rank,
                'quizzes_count': row['quizzes_count'],
                'average_score': round(row['average_score'] or 0, 1),
                'total_points': row['total_points'] or 0,
                'is_current_user': row['user_id'] == auth_user.id,
            })
        return Response(payload)

    elif request.method == 'POST':
        user = auth_user
        quiz_title = request.data.get('quizTitle', 'Quiz Concours')
        try:
            score = int(request.data.get('score', 0))
            total = int(request.data.get('total', 10))
        except (TypeError, ValueError):
            return Response({'error': 'Score invalide.'}, status=status.HTTP_400_BAD_REQUEST)
        if total <= 0 or score < 0 or score > total:
            return Response({'error': 'Le score doit être compris entre 0 et le total.'}, status=status.HTTP_400_BAD_REQUEST)
        pct = round((score / max(1, total)) * 100, 1)

        attempt = QuizAttempt.objects.create(
            user=user,
            quiz_title=quiz_title,
            score=score,
            total=total,
            percentage=pct
        )
        return Response(QuizAttemptSerializer(attempt).data, status=status.HTTP_201_CREATED)

# --- CALENDAR EVENTS COMPARTMENT ---

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def calendar_events_list_create(request):
    user = request_user(request)
    if not user:
        return auth_error()
    if request.method == 'GET':
        events = CalendarEvent.objects.filter(Q(user=user) | Q(user__isnull=True)).order_by('event_date')
        return Response(CalendarEventSerializer(events, many=True).data)

    elif request.method == 'POST':
        title = request.data.get('title')
        concourse_name = request.data.get('concourseName')
        event_type = request.data.get('eventType', 'ecrit')
        event_date = request.data.get('eventDate')
        description = request.data.get('description', '')
        event_time = request.data.get('eventTime') or None

        if not title or not event_date:
            return Response({'error': 'Le titre et la date sont obligatoires.'}, status=status.HTTP_400_BAD_REQUEST)

        evt = CalendarEvent.objects.create(
            user=user,
            title=title,
            concourse_name=concourse_name,
            event_type=event_type,
            event_date=event_date,
            event_time=event_time,
            description=description
        )
        return Response(CalendarEventSerializer(evt).data, status=status.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
@permission_classes([AllowAny])
def calendar_event_detail(request, pk):
    user = request_user(request)
    if not user:
        return auth_error()
    event = CalendarEvent.objects.filter(pk=pk, user=user).first()
    if not event:
        return Response({'error': 'Événement introuvable ou non modifiable.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'DELETE':
        event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    for incoming, model_field in {'title': 'title', 'eventDate': 'event_date', 'eventTime': 'event_time',
                                  'eventType': 'event_type', 'concourseName': 'concourse_name',
                                  'description': 'description', 'completed': 'completed'}.items():
        if incoming in request.data:
            setattr(event, model_field, request.data[incoming])
    event.save()
    return Response(CalendarEventSerializer(event).data)

# --- ADMIN MANAGEMENT VIEWS ---

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def admin_users_list_create(request):
    auth_user = request_user(request)
    if not has_role(auth_user, 'admin'):
        return role_error() if auth_user else auth_error()
    if request.method == 'GET':
        users = User.objects.all()
        return Response(UserSerializer(users, many=True).data)

    elif request.method == 'POST':
        name = request.data.get('name')
        email = request.data.get('email')
        password = request.data.get('password', '')
        role = request.data.get('role', 'candidat')

        if role not in dict(UserProfile.ROLE_CHOICES):
            return Response({'error': 'Rôle invalide.'}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email__iexact=email).exists():
            return Response({'error': 'Email déjà pris.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(password) < 10:
            return Response({'error': 'Un mot de passe initial de 10 caractères minimum est requis.'}, status=status.HTTP_400_BAD_REQUEST)

        username = email.split('@')[0] + "_" + uuid.uuid4().hex[:4]
        user = User.objects.create_user(username=username, email=email, password=password, first_name=name)
        UserProfile.objects.create(user=user, role=role, status='active')
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

@api_view(['PATCH'])
@permission_classes([AllowAny])
def admin_user_update(request, pk):
    auth_user = request_user(request)
    if not has_role(auth_user, 'admin'):
        return role_error() if auth_user else auth_error()
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return Response({'error': 'Utilisateur introuvable.'}, status=status.HTTP_404_NOT_FOUND)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    if 'status' in request.data:
        if request.data['status'] not in dict(UserProfile.STATUS_CHOICES):
            return Response({'error': 'Statut invalide.'}, status=status.HTTP_400_BAD_REQUEST)
        profile.status = request.data['status']
    if 'role' in request.data:
        if request.data['role'] not in dict(UserProfile.ROLE_CHOICES):
            return Response({'error': 'Rôle invalide.'}, status=status.HTTP_400_BAD_REQUEST)
        profile.role = request.data['role']
    profile.save()
    return Response(UserSerializer(user).data)

@api_view(['GET'])
@permission_classes([AllowAny])
def admin_overview(request):
    user = request_user(request)
    if not has_role(user, 'admin'):
        return role_error() if user else auth_error()
    total_users = User.objects.count()
    active_candidates = UserProfile.objects.filter(role='candidat', status='active').count()
    active_concours = Concours.objects.filter(active=True).count()
    pending_moderation = Submission.objects.filter(status='pending').count()

    content_by_kind = {row['kind']: row['total'] for row in LearningContent.objects.values('kind').annotate(total=Count('id'))}
    users_by_role = {row['role']: row['total'] for row in UserProfile.objects.values('role').annotate(total=Count('id'))}
    return Response({
        'users': total_users,
        'activeCandidates': active_candidates,
        'activeConcours': active_concours,
        'pendingModeration': pending_moderation,
        'enrollments': Enrollment.objects.count(),
        'resources': Resource.objects.filter(status='published').count(),
        'publishedContents': LearningContent.objects.filter(status='published').count(),
        'verifiedConcours': Concours.objects.filter(active=True).exclude(source_url='').count(),
        'messages': TutorMessage.objects.count(),
        'activities': Activity.objects.count(),
        'workToReview': CandidateWorkSubmission.objects.filter(status='submitted').count(),
        'usersByRole': users_by_role,
        'contentByKind': content_by_kind,
        'recentUsers': [
            {'id': item.id, 'name': item.get_full_name() or item.username, 'email': item.email,
             'role': UserProfile.objects.filter(user_id=item.id).values_list('role', flat=True).first() or ('admin' if item.is_superuser else 'non configuré'),
             'joinedAt': item.date_joined}
            for item in User.objects.order_by('-date_joined')[:6]
        ],
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def teacher_overview(request):
    user = request_user(request)
    if not has_role(user, 'enseignant'):
        return role_error() if user else auth_error()
    own_contents = LearningContent.objects.filter(author=user)
    own_progress = UserProgress.objects.filter(content__author=user).select_related('user', 'content')
    reached_ids = set(own_progress.values_list('user_id', flat=True))
    reached_ids.update(CandidateWorkSubmission.objects.filter(teacher=user).values_list('candidate_id', flat=True))
    exchanges = TutorMessage.objects.filter(Q(sender=user) | Q(recipient=user))
    reached_ids.update(exchanges.values_list('sender_id', flat=True))
    reached_ids.update(exchanges.values_list('recipient_id', flat=True))
    reached_ids.discard(user.id)
    candidates = User.objects.filter(pk__in=reached_ids, profile__role='candidat', profile__status='active')
    return Response({
        'learnersReached': candidates.count(),
        'publishedContents': own_contents.filter(status='published').count(),
        'pendingContents': Submission.objects.filter(author=user, status='pending').count(),
        'appointments': TutorAppointment.objects.filter(tutor=user, status__in=['pending', 'confirmed']).count(),
        'averageProgressScore': own_progress.aggregate(value=Avg('score'))['value'],
        'completedLearningUnits': own_progress.filter(completed=True).count(),
        'messagesWaiting': TutorMessage.objects.filter(recipient=user, read=False).count(),
        'workToReview': CandidateWorkSubmission.objects.filter(teacher=user, status='submitted').count(),
        'recentContent': LearningContentSerializer(own_contents.order_by('-updated_at')[:6], many=True).data,
        'candidatePerformance': [
            {
                'id': candidate.id,
                'name': candidate.get_full_name() or candidate.username,
                'interactions': own_progress.filter(user=candidate).count(),
                'completed': own_progress.filter(user=candidate, completed=True).count(),
                'averageScore': own_progress.filter(user=candidate).aggregate(value=Avg('score'))['value'],
            }
            for candidate in candidates[:100]
        ],
    })


# --- PERSISTENT LEARNING DATA ---

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def content_list_create(request):
    if request.method == 'GET':
        user = request_user(request)
        mine = request.query_params.get('mine') == '1'
        if mine:
            if not has_role(user, 'enseignant', 'admin'):
                return role_error() if user else auth_error()
            qs = LearningContent.objects.select_related('concourse', 'author').filter(author=user)
        else:
            qs = LearningContent.objects.select_related('concourse', 'author').filter(status='published')
        qs = qs.filter(Q(is_private=False) | Q(author=user)) if user else qs.filter(is_private=False)
        kind = request.query_params.get('kind')
        concourse_code = request.query_params.get('concourseCode')
        if kind:
            qs = qs.filter(kind=kind)
        if concourse_code:
            qs = qs.filter(Q(concourse__id_code=concourse_code) | Q(concourse__isnull=True))
        return Response(LearningContentSerializer(qs.order_by('title'), many=True).data)

    user = request_user(request)
    requested_kind = request.data.get('kind')
    if not user:
        return auth_error()
    if requested_kind != 'flashcard' and not has_role(user, 'enseignant', 'admin'):
        return role_error() if user else auth_error()
    if requested_kind not in dict(LearningContent.KIND_CHOICES) or not str(request.data.get('title', '')).strip():
        return Response({'error': 'Type de contenu et titre valides requis.'}, status=status.HTTP_400_BAD_REQUEST)
    payload = request.data.copy()
    concourse = concours_from_value(payload.pop('concourseCode', None) or payload.get('concourse'))
    slug = payload.get('slug') or f"{payload.get('kind', 'content')}-{uuid.uuid4().hex[:10]}"
    is_candidate_flashcard = requested_kind == 'flashcard' and not has_role(user, 'enseignant', 'admin')
    requested_status = payload.get('status', 'draft')
    content_status = requested_status if has_role(user, 'admin') else ('published' if is_candidate_flashcard else 'draft')
    item = LearningContent.objects.create(
        kind=payload.get('kind'), slug=slug, title=payload.get('title'),
        concourse=concourse, data=payload.get('data', {}), author=user,
        status=content_status, source_name=payload.get('sourceName', ''),
        source_url=payload.get('sourceUrl', ''),
        verified_at=timezone.now() if payload.get('verified') else None,
        is_private=True if is_candidate_flashcard else bool(payload.get('isPrivate', False)),
    )
    return Response(LearningContentSerializer(item).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([AllowAny])
def content_detail(request, pk):
    item = LearningContent.objects.filter(pk=pk).first()
    if not item:
        return Response({'error': 'Contenu introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        viewer = request_user(request)
        if item.status != 'published' and not (has_role(viewer, 'admin') or (viewer and item.author_id == viewer.id)):
            return role_error() if viewer else auth_error()
        return Response(LearningContentSerializer(item).data)
    user = request_user(request)
    if not has_role(user, 'enseignant', 'admin'):
        return role_error() if user else auth_error()
    if not has_role(user, 'admin') and item.author_id != user.id:
        return role_error()
    if not has_role(user, 'admin') and ('status' in request.data or request.data.get('verified')):
        return Response({'error': 'Seul un administrateur peut publier ou vérifier un contenu.'}, status=status.HTTP_403_FORBIDDEN)
    if request.method == 'DELETE':
        item.status = 'archived'
        item.save(update_fields=['status', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)
    field_map = {'kind': 'kind', 'slug': 'slug', 'title': 'title', 'data': 'data', 'status': 'status',
                 'sourceName': 'source_name', 'sourceUrl': 'source_url'}
    for incoming, model_field in field_map.items():
        if incoming in request.data:
            setattr(item, model_field, request.data[incoming])
    if 'concourseCode' in request.data:
        item.concourse = concours_from_value(request.data['concourseCode'])
    if request.data.get('verified'):
        item.verified_at = timezone.now()
    item.save()
    return Response(LearningContentSerializer(item).data)


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([AllowAny])
def enrollments_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    if request.method == 'GET':
        return Response(EnrollmentSerializer(Enrollment.objects.filter(user=user).select_related('concourse'), many=True).data)
    concours = concours_from_value(request.data.get('concourseId') or request.query_params.get('concourseId'))
    if not concours:
        return Response({'error': 'Concours introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'DELETE':
        Enrollment.objects.filter(user=user, concourse=concours).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    enrollment, created = Enrollment.objects.get_or_create(user=user, concourse=concours)
    return Response(EnrollmentSerializer(enrollment).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def progress_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    if request.method == 'GET':
        qs = UserProgress.objects.filter(user=user).select_related('content')
        if request.query_params.get('kind'):
            qs = qs.filter(content__kind=request.query_params['kind'])
        return Response(UserProgressSerializer(qs, many=True).data)
    content = LearningContent.objects.filter(pk=request.data.get('contentId'), status='published').first()
    if not content:
        return Response({'error': 'Contenu introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    item, _ = UserProgress.objects.update_or_create(
        user=user, content=content,
        defaults={'progress': request.data.get('progress', {}), 'completed': bool(request.data.get('completed', False)),
                  'score': request.data.get('score')}
    )
    return Response(UserProgressSerializer(item).data)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def activities_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    if request.method == 'GET':
        qs = Activity.objects.filter(user=user).select_related('concourse').order_by('-created_at')
        if request.query_params.get('type'):
            qs = qs.filter(activity_type=request.query_params['type'])
        return Response(ActivitySerializer(qs[:200], many=True).data)
    concours = concours_from_value(request.data.get('concourseId'))
    item = Activity.objects.create(
        user=user, activity_type=request.data.get('activityType'), title=request.data.get('title'),
        concourse=concours, score=request.data.get('score'), total=request.data.get('total'),
        duration_seconds=max(0, int(request.data.get('durationSeconds', 0))), details=request.data.get('details', {}),
    )
    return Response(ActivitySerializer(item).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([AllowAny])
def activity_summary(request):
    user = request_user(request)
    if not user:
        return auth_error()
    qs = Activity.objects.filter(user=user)
    scored = qs.exclude(score__isnull=True).exclude(total__isnull=True)
    percentages = [a.score / a.total * 100 for a in scored if a.total]
    study_seconds = StudySession.objects.filter(user=user).aggregate(v=Sum('duration_seconds'))['v'] or 0
    assessment_seconds = qs.aggregate(v=Sum('duration_seconds'))['v'] or 0
    return Response({
        'activities': qs.count(),
        'completedQuizzes': qs.filter(activity_type='quiz').count(),
        'studyHours': round(study_seconds / 3600, 2),
        'simulationHours': round(study_seconds / 3600, 2),
        'assessmentHours': round(assessment_seconds / 3600, 2),
        'averageScore': round(sum(percentages) / len(percentages), 1) if percentages else None,
        'completedCourses': UserProgress.objects.filter(user=user, content__kind='course', completed=True).count(),
        'flashcardsMastered': UserProgress.objects.filter(user=user, content__kind='flashcard', completed=True).count(),
    })


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def study_sessions_view(request):
    user = request_user(request)
    if not user:
        return auth_error()

    def totals(item=None):
        total = StudySession.objects.filter(user=user).aggregate(v=Sum('duration_seconds'))['v'] or 0
        today = StudySession.objects.filter(user=user, started_at__date=timezone.localdate()).aggregate(v=Sum('duration_seconds'))['v'] or 0
        return {
            'sessionSeconds': item.duration_seconds if item else 0,
            'todaySeconds': today,
            'totalSeconds': total,
            'totalHours': round(total / 3600, 2),
        }

    if request.method == 'GET':
        return Response(totals())

    session_key = str(request.data.get('sessionKey', '')).strip()[:64]
    if not session_key:
        return Response({'error': 'Identifiant de session requis.'}, status=status.HTTP_400_BAD_REQUEST)
    now = timezone.now()
    item, created = StudySession.objects.get_or_create(
        user=user, session_key=session_key,
        defaults={'last_heartbeat': now, 'context': request.data.get('context') or {}},
    )
    if not created and item.ended_at is None:
        elapsed = max(0, int((now - item.last_heartbeat).total_seconds()))
        if elapsed <= 90:
            item.duration_seconds += min(elapsed, 60)
        item.last_heartbeat = now
        item.context = request.data.get('context') or item.context
    if request.data.get('action') == 'end':
        item.ended_at = now
    item.save(update_fields=['duration_seconds', 'last_heartbeat', 'ended_at', 'context'])
    return Response(totals(item), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['GET', 'PATCH'])
@permission_classes([AllowAny])
def notifications_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    qs = Notification.objects.filter(user=user).order_by('-created_at')
    if request.method == 'GET':
        return Response(NotificationSerializer(qs[:100], many=True).data)
    notification_id = request.data.get('id')
    target = qs.filter(pk=notification_id) if notification_id else qs
    target.update(read=True)
    return Response({'updated': target.count()})


@api_view(['GET'])
@permission_classes([AllowAny])
def tutors_view(request):
    tutors = User.objects.filter(profile__role='enseignant', profile__status='active').select_related('profile')
    return Response(UserSerializer(tutors, many=True).data)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def tutor_messages_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    other_id = request.query_params.get('with') or request.data.get('recipientId')
    if request.method == 'GET':
        qs = TutorMessage.objects.filter(Q(sender=user) | Q(recipient=user)).select_related('sender', 'recipient')
        if other_id:
            qs = qs.filter(Q(sender_id=other_id) | Q(recipient_id=other_id))
        qs.filter(recipient=user, read=False).update(read=True)
        return Response(TutorMessageSerializer(qs.order_by('created_at')[:500], many=True).data)
    recipient = User.objects.filter(pk=other_id, profile__status='active').first()
    text_value = str(request.data.get('text', '')).strip()
    if not recipient or not text_value:
        return Response({'error': 'Destinataire et message requis.'}, status=status.HTTP_400_BAD_REQUEST)
    item = TutorMessage.objects.create(sender=user, recipient=recipient, text=text_value,
                                       attachment_url=request.data.get('attachmentUrl', ''))
    recipient_role = getattr(getattr(recipient, 'profile', None), 'role', '')
    Notification.objects.create(
        user=recipient, title='Nouveau message',
        message=f"{user.get_full_name() or user.email} vous a envoyé un message.",
        type='tutor', action_url='/teacher/messages' if recipient_role == 'enseignant' else '/tutors',
    )
    return Response(TutorMessageSerializer(item).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'POST', 'PATCH'])
@permission_classes([AllowAny])
def appointments_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    if request.method == 'GET':
        qs = TutorAppointment.objects.filter(Q(candidate=user) | Q(tutor=user)).select_related('candidate', 'tutor')
        return Response(TutorAppointmentSerializer(qs.order_by('-scheduled_at'), many=True).data)
    if request.method == 'PATCH':
        item = TutorAppointment.objects.filter(pk=request.data.get('id')).filter(Q(candidate=user) | Q(tutor=user)).first()
        if not item:
            return Response({'error': 'Rendez-vous introuvable.'}, status=status.HTTP_404_NOT_FOUND)
        requested_status = request.data.get('status')
        if user.id == item.tutor_id:
            if requested_status not in ['confirmed', 'rejected', 'completed']:
                return Response({'error': 'Le professeur peut confirmer, refuser ou terminer le rendez-vous.'}, status=status.HTTP_400_BAD_REQUEST)
            allowed_transitions = {
                'pending': ['confirmed', 'rejected'],
                'confirmed': ['completed'],
                'rejected': [], 'cancelled': [], 'completed': [],
            }
            if requested_status not in allowed_transitions.get(item.status, []):
                return Response({'error': 'Cette transition de rendez-vous n’est pas autorisée.'}, status=status.HTTP_400_BAD_REQUEST)
            previous_status = item.status
            item.status = requested_status
            item.save(update_fields=['status'])
            if previous_status != requested_status:
                labels = {'confirmed': 'confirmé', 'rejected': 'refusé', 'completed': 'marqué comme terminé'}
                Notification.objects.create(
                    user=item.candidate, title=f"Rendez-vous {labels[requested_status]}",
                    message=f"Votre rendez-vous « {item.topic} » avec {item.tutor.get_full_name() or item.tutor.email} a été {labels[requested_status]}.",
                    type='tutor', action_url='/tutors',
                )
        elif requested_status == 'cancelled':
            if item.status not in ['pending', 'confirmed']:
                return Response({'error': 'Ce rendez-vous ne peut plus être annulé.'}, status=status.HTTP_400_BAD_REQUEST)
            previous_status = item.status
            item.status = 'cancelled'
            item.save(update_fields=['status'])
            if previous_status != 'cancelled':
                Notification.objects.create(
                    user=item.tutor, title='Rendez-vous annulé par le candidat',
                    message=f"{item.candidate.get_full_name() or item.candidate.email} a annulé « {item.topic} ».",
                    type='tutor', action_url='/teacher/grading',
                )
        else:
            return role_error()
        return Response(TutorAppointmentSerializer(item).data)
    tutor = User.objects.filter(pk=request.data.get('tutorId'), profile__role='enseignant', profile__status='active').first()
    scheduled_at = parse_datetime(str(request.data.get('scheduledAt', '')))
    if not tutor or not scheduled_at or not request.data.get('topic'):
        return Response({'error': 'Tuteur, date et sujet sont requis.'}, status=status.HTTP_400_BAD_REQUEST)
    item = TutorAppointment.objects.create(candidate=user, tutor=tutor, scheduled_at=scheduled_at,
                                           topic=request.data['topic'], status='pending')
    Notification.objects.create(user=tutor, title='Nouvelle demande de rendez-vous',
                                message=f"{user.get_full_name() or user.email} demande un rendez-vous pour « {item.topic} ».",
                                type='tutor', action_url='/teacher/grading')
    return Response(TutorAppointmentSerializer(item).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def subscriptions_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    if request.method == 'GET':
        return Response(SubscriptionSerializer(Subscription.objects.filter(user=user).select_related('plan').order_by('-updated_at'), many=True).data)
    plan = LearningContent.objects.filter(pk=request.data.get('planId'), kind='subscription_plan', status='published').first()
    if not plan:
        return Response({'error': 'Formule introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    price = float(plan.data.get('priceAmount', 0) or 0)
    
    checkout_url = ''
    campay_ref = ''
    campay_username = os.getenv('CAMPAY_USERNAME', '').strip()
    campay_password = os.getenv('CAMPAY_PASSWORD', '').strip()
    campay_env = os.getenv('CAMPAY_ENVIRONMENT', 'demo').strip().lower()
    
    if price > 0:
        if campay_username and campay_password:
            import urllib.request
            import urllib.parse
            base_url = 'https://demo.campay.net/api/' if campay_env == 'demo' else 'https://campay.net/api/'
            try:
                # 1. Obtenir le token de connexion Campay
                token_url = f"{base_url}token/"
                token_data = json.dumps({
                    'username': campay_username,
                    'password': campay_password
                }).encode('utf-8')
                req = urllib.request.Request(token_url, data=token_data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    token_res = json.loads(response.read().decode('utf-8'))
                    access_token = token_res.get('token')
                
                user_phone = str(request.data.get('phone', '') or request.data.get('phoneNumber', '')).strip()
                if user_phone:
                    user_phone = ''.join(c for c in user_phone if c.isdigit())
                    if len(user_phone) == 9 and user_phone.startswith(('6', '2')):
                        user_phone = f"237{user_phone}"
                
                pay_amount = '10' if campay_env == 'demo' else str(max(10, int(price)))
                ext_ref = f"SUB-{user.id}-{plan.id}-{int(timezone.now().timestamp())}"
                
                if access_token and user_phone and len(user_phone) >= 9:
                    collect_url = f"{base_url}collect/"
                    col_payload = {
                        'amount': pay_amount,
                        'currency': 'XAF',
                        'from': user_phone,
                        'description': f"Abonnement {plan.title}"[:100],
                        'external_reference': ext_ref
                    }
                    req_col = urllib.request.Request(
                        collect_url,
                        data=json.dumps(col_payload).encode('utf-8'),
                        headers={
                            'Content-Type': 'application/json',
                            'Authorization': f'Token {access_token}'
                        }
                    )
                    try:
                        with urllib.request.urlopen(req_col, timeout=12) as resp_col:
                            col_res = json.loads(resp_col.read().decode('utf-8'))
                            campay_ref = col_res.get('reference', '')
                            ussd_code = col_res.get('ussd_code', '')
                            operator_name = col_res.get('operator', '')
                    except Exception:
                        pass
                
                if access_token and not campay_ref:
                    pay_url = f"{base_url}get_payment_link/"
                    pay_payload = {
                        'amount': pay_amount,
                        'currency': 'XAF',
                        'description': f"Abonnement {plan.title}"[:100],
                        'external_reference': ext_ref
                    }
                    req_pay = urllib.request.Request(
                        pay_url,
                        data=json.dumps(pay_payload).encode('utf-8'),
                        headers={
                            'Content-Type': 'application/json',
                            'Authorization': f'Token {access_token}'
                        }
                    )
                    with urllib.request.urlopen(req_pay, timeout=10) as resp_pay:
                        pay_res = json.loads(resp_pay.read().decode('utf-8'))
                        checkout_url = pay_res.get('link') or pay_res.get('action_url') or pay_res.get('payment_url', '')
                        campay_ref = pay_res.get('reference', '')
            except Exception as e:
                checkout_url = os.getenv('PAYMENT_CHECKOUT_URL', '').strip()
                if not checkout_url and not campay_ref:
                    return Response({'error': f'Erreur lors de l’initialisation du paiement Campay ({str(e)}).'},
                                    status=status.HTTP_502_BAD_GATEWAY)
        else:
            checkout_url = os.getenv('PAYMENT_CHECKOUT_URL', '').strip()

        if not checkout_url and not campay_ref:
            return Response({'error': 'Le prestataire de paiement réel Campay n’est pas configuré.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

    target_status = 'active' if price == 0 else 'pending'
    if price == 0:
        Subscription.objects.filter(user=user, status__in=['active', 'pending']).exclude(plan=plan).update(status='cancelled')
    else:
        # Quand un nouvel abonnement payant est initialisé, désactiver tout abonnement temporaire/obsolète
        Subscription.objects.filter(user=user, status='pending').exclude(plan=plan).update(status='cancelled')

    payment_method_str = f"campay:{campay_ref}" if campay_ref else request.data.get('paymentMethod', 'campay')
    item, _ = Subscription.objects.update_or_create(
        user=user, plan=plan,
        defaults={'status': target_status, 'payment_method': payment_method_str},
    )
    if price == 0:
        user.profile.is_premium = False
        user.profile.save(update_fields=['is_premium'])
    payload = SubscriptionSerializer(item).data
    if price > 0:
        payload['checkoutUrl'] = checkout_url
    Notification.objects.create(
        user=user,
        title='Abonnement activé' if target_status == 'active' else 'Paiement Campay initialisé',
        message=f"Votre formule « {plan.title} » est {'active' if target_status == 'active' else 'en attente de règlement (10 FCFA Démo via Campay)'}.",
        type='system', action_url='/pricing',
    )
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_subscription_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    sub_id = request.data.get('subscriptionId')
    sub = Subscription.objects.filter(pk=sub_id, user=user).first() if sub_id else Subscription.objects.filter(user=user, status='pending').first()
    if not sub:
        # Si aucun abonnement en attente, prendre le dernier abonnement créé pour l'activer
        sub = Subscription.objects.filter(user=user).order_by('-created_at').first()
    if not sub:
        return Response({'error': 'Aucun abonnement trouvé pour ce compte.'}, status=status.HTTP_404_NOT_FOUND)
    
    # Désactiver tout autre abonnement (ex: Découverte 0 FCFA) pour activer uniquement l'abonnement souscrit
    Subscription.objects.filter(user=user).exclude(pk=sub.pk).update(status='cancelled')
    sub.status = 'active'
    sub.save(update_fields=['status', 'updated_at'])
    user.profile.is_premium = True
    user.profile.save(update_fields=['is_premium'])
    
    Notification.objects.create(
        user=user,
        title='Abonnement Premium activé !',
        message=f"Félicitations ! Votre abonnement « {sub.plan.title} » est désormais totalement actif via Campay.",
        type='system', action_url='/pricing',
    )
    return Response({
        'status': 'active',
        'is_premium': True,
        'subscription': SubscriptionSerializer(sub).data
    })


@api_view(['GET', 'POST', 'PATCH'])
@permission_classes([AllowAny])
def work_submissions_view(request):
    user = request_user(request)
    if not user:
        return auth_error()
    role = getattr(user.profile, 'role', '')
    if request.method == 'GET':
        qs = CandidateWorkSubmission.objects.select_related('candidate', 'teacher', 'concourse', 'resource')
        if role == 'candidat':
            qs = qs.filter(candidate=user)
        elif role == 'enseignant':
            qs = qs.filter(teacher=user)
        elif role != 'admin':
            return role_error()
        return Response(CandidateWorkSubmissionSerializer(qs.order_by('-created_at')[:300], many=True).data)

    if request.method == 'POST':
        if role != 'candidat':
            return role_error()
        title = str(request.data.get('title', '')).strip()
        question = str(request.data.get('question', '')).strip()
        answer = str(request.data.get('answer', '')).strip()
        if not title or not question or len(answer) < 10:
            return Response({'error': 'Titre, sujet et réponse d’au moins 10 caractères requis.'}, status=status.HTTP_400_BAD_REQUEST)
        teacher = User.objects.filter(pk=request.data.get('teacherId'), profile__role='enseignant', profile__status='active').first()
        if request.data.get('teacherId') and not teacher:
            return Response({'error': 'Enseignant introuvable ou indisponible.'}, status=status.HTTP_400_BAD_REQUEST)
        concourse = concours_from_value(request.data.get('concourseId'))
        resource = Resource.objects.filter(pk=request.data.get('resourceId'), status='published').first()
        rubric = str(request.data.get('rubric', ''))
        evaluation_token = str(request.data.get('evaluationToken', '')).strip()
        activity_id = request.data.get('activityId')
        if evaluation_token:
            try:
                signed_evaluation = signing.loads(evaluation_token, salt='prepconcours-evaluation-v1', max_age=86400)
            except (signing.BadSignature, signing.SignatureExpired):
                return Response({'error': 'La note affichée a expiré ou n’est plus valide. Relancez la correction avant l’envoi.'}, status=status.HTTP_400_BAD_REQUEST)
            expected_fingerprint = evaluation_fingerprint(
                question, answer, rubric, request.data.get('evaluationMode', 'written'), request.data.get('language', ''),
            )
            if signed_evaluation.get('userId') != user.id or signed_evaluation.get('fingerprint') != expected_fingerprint:
                return Response({'error': 'La note ne correspond pas exactement à cette copie. Relancez la correction.'}, status=status.HTTP_400_BAD_REQUEST)
            evaluation = signed_evaluation.get('evaluation')
            if not isinstance(evaluation, dict) or not isinstance(evaluation.get('score'), (int, float)):
                return Response({'error': 'Évaluation signée invalide.'}, status=status.HTTP_400_BAD_REQUEST)
        elif activity_id:
            activity = Activity.objects.filter(pk=activity_id, user=user, activity_type='exam').first()
            if not activity or activity.score is None or not activity.total or not title.startswith(activity.title):
                return Response({'error': 'Le résultat enregistré ne correspond pas à cet examen.'}, status=status.HTTP_400_BAD_REQUEST)
            if activity.concourse_id and concourse and activity.concourse_id != concourse.id:
                return Response({'error': 'Le résultat enregistré appartient à un autre concours.'}, status=status.HTTP_400_BAD_REQUEST)
            recorded_score = round(float(activity.score) / float(activity.total) * 20, 1)
            evaluation = {
                'score': recorded_score, 'maxScore': 20,
                'strengths': ['La moyenne reprend les résultats enregistrés pour chaque épreuve terminée.'],
                'improvements': ['Consultez le détail des épreuves puis faites confirmer la correction par le professeur.'],
                'detailedFeedback': f'Moyenne pondérée enregistrée à la fin de l’examen blanc : {recorded_score}/20.',
                'breakdown': {'examActivityId': activity.id, 'components': activity.details},
                'engine': 'recorded-exam-composite-v1', 'isOfficial': False, 'eliminatory': recorded_score == 0,
            }
        else:
            evaluation = grade_open_answer(question, answer, rubric)
        item = CandidateWorkSubmission.objects.create(
            candidate=user, teacher=teacher, concourse=concourse, resource=resource,
            title=title, question=question, answer=answer, local_evaluation=evaluation,
        )
        if teacher:
            Notification.objects.create(
                user=teacher, title='Nouvelle copie à corriger',
                message=f"{user.get_full_name() or user.email} a soumis « {title} ».",
                type='tutor', action_url='/teacher/grading',
            )
        return Response(CandidateWorkSubmissionSerializer(item).data, status=status.HTTP_201_CREATED)

    if role not in ['enseignant', 'admin']:
        return role_error()
    item = CandidateWorkSubmission.objects.filter(pk=request.data.get('id')).first()
    if not item or (role == 'enseignant' and item.teacher_id != user.id):
        return Response({'error': 'Copie introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        score = float(request.data.get('teacherScore'))
    except (TypeError, ValueError):
        return Response({'error': 'Une note numérique est requise.'}, status=status.HTTP_400_BAD_REQUEST)
    if score < 0 or score > 20:
        return Response({'error': 'La note doit être comprise entre 0 et 20.'}, status=status.HTTP_400_BAD_REQUEST)
    feedback = str(request.data.get('teacherFeedback', '')).strip()
    if len(feedback) < 5:
        return Response({'error': 'Ajoutez une appréciation utile.'}, status=status.HTTP_400_BAD_REQUEST)
    item.teacher_score = score
    item.teacher_feedback = feedback
    item.status = request.data.get('status') if request.data.get('status') in ['reviewed', 'returned'] else 'reviewed'
    item.save(update_fields=['teacher_score', 'teacher_feedback', 'status', 'updated_at'])
    Notification.objects.create(
        user=item.candidate, title='Votre copie a été corrigée',
        message=f"{item.title} : {score}/20. Consultez l’appréciation de votre enseignant.",
        type='tutor', action_url='/past-papers',
    )
    return Response(CandidateWorkSubmissionSerializer(item).data)

# --- GEMINI AI INTEGRATION VIEWS ---

@api_view(['POST'])
@permission_classes([AllowAny])
def gemini_jury_eval(request):
    user = request_user(request)
    if not user:
        return auth_error()
    concourse = request.data.get('concourse')
    question = request.data.get('question')
    transcript = request.data.get('transcript')
    duration = request.data.get('duration')

    eval_result = evaluate_oral_jury(concourse, question, transcript, duration)
    if eval_result.get('serviceUnavailable'):
        return Response(eval_result, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    OralSession.objects.create(
        user=user,
        concourse_name=concourse or 'Général',
        question=question or '',
        transcript=transcript or '',
        duration=duration or '01:30',
        evaluation_json=eval_result
    )

    return Response(eval_result)

@api_view(['POST'])
@permission_classes([AllowAny])
def gemini_tutor_chat(request):
    user = request_user(request)
    if not user:
        return auth_error()
    tutor_name = request.data.get('tutorName')
    tutor_role = request.data.get('tutorRole')
    history = request.data.get('history', [])
    message = request.data.get('message', '')

    if not str(message).strip():
        return Response({'error': 'Écrivez une question.'}, status=status.HTTP_400_BAD_REQUEST)
    grounded = grounded_catalog_reply(message)
    if grounded.get('engine') != 'local-catalog-no-match':
        return Response(grounded)
    result = tutor_chat_reply(tutor_name, tutor_role, history, message)
    if result.get('serviceUnavailable'):
        result = grounded
    return Response(result)

@api_view(['POST'])
@permission_classes([AllowAny])
def gemini_generate_quiz(request):
    user = request_user(request)
    if not user:
        return auth_error()
    doc_text = request.data.get('documentText', '')
    doc_title = request.data.get('documentTitle', '')
    count = request.data.get('questionCount', 5)
    target = request.data.get('concourseTarget', '')

    quiz_data = generate_quiz_from_text(doc_text, doc_title, count, target)
    if quiz_data.get('serviceUnavailable'):
        return Response(quiz_data, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if quiz_data.get('error'):
        return Response(quiz_data, status=status.HTTP_400_BAD_REQUEST)

    Quiz.objects.create(
        title=quiz_data.get('title', doc_title or 'Quiz IA'),
        concourse_target=target,
        questions_data=quiz_data.get('questions', []),
        author=user,
    )

    return Response(quiz_data)


@api_view(['POST'])
@permission_classes([AllowAny])
def gemini_generate_material(request):
    user = request_user(request)
    if not user:
        return auth_error()
    result = generate_material_from_text(request.data.get('documentText', ''), request.data.get('mode', ''), request.data.get('concourseTarget', ''))
    if result.get('serviceUnavailable'):
        return Response(result, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(result, status=status.HTTP_400_BAD_REQUEST if result.get('error') else status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([AllowAny])
def gemini_orientation_chat(request):
    user = request_user(request)
    if not user:
        return auth_error()
    diploma = request.data.get('diploma')
    interest = request.data.get('interest')
    experience = request.data.get('experience')
    message = request.data.get('message')

    result = orientation_advisor(diploma, interest, experience, message)
    if result.get('serviceUnavailable'):
        result = grounded_orientation(diploma, interest or message, experience)
    return Response(result)


@api_view(['POST'])
@permission_classes([AllowAny])
def extract_document_text(request):
    user = request_user(request)
    if not user:
        return auth_error()
    file_name = str(request.data.get('fileName', '')).lower()
    encoded = str(request.data.get('dataBase64', ''))
    if not file_name.endswith('.pdf') or not encoded:
        return Response({'error': 'Seuls les fichiers PDF sont acceptés par cet extracteur.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        raw_payload = encoded.split(',', 1)[-1]
        if len(raw_payload) > 12_000_000:
            return Response({'error': 'Le PDF dépasse la limite autorisée de 8 Mo.'}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        raw = base64.b64decode(raw_payload, validate=True)
        if len(raw) > 8_000_000:
            return Response({'error': 'Le PDF dépasse la limite autorisée de 8 Mo.'}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        if len(reader.pages) > 80:
            return Response({'error': 'Le PDF dépasse la limite de 80 pages.'}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        text_value = '\n\n'.join((page.extract_text() or '').strip() for page in reader.pages).strip()
        if len(text_value) < 80:
            return Response({'error': 'Ce PDF ne contient pas assez de texte extractible. Il peut s’agir d’un scan image.'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response({'text': text_value[:120_000], 'pages': len(reader.pages)})
    except Exception:
        return Response({'error': 'Le PDF est illisible ou protégé.'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

@api_view(['POST'])
@permission_classes([AllowAny])
def gemini_grade_answer(request):
    user = request_user(request)
    if not user:
        return auth_error()
    question = request.data.get('question')
    answer = request.data.get('candidateAnswer')
    rubric = request.data.get('rubric')
    evaluation_mode = request.data.get('evaluationMode', 'written')
    language = request.data.get('language', '')

    result = (local_code_grade(question, answer, rubric, language)
              if evaluation_mode == 'code'
              else grade_open_answer(question, answer, rubric))
    if not result.get('serviceUnavailable'):
        signed_payload = {
            'userId': user.id,
            'fingerprint': evaluation_fingerprint(question, answer, rubric, evaluation_mode, language),
            'evaluation': result,
        }
        result = {**result, 'evaluationToken': signing.dumps(signed_payload, salt='prepconcours-evaluation-v1', compress=True)}
    return Response(result, status=status.HTTP_503_SERVICE_UNAVAILABLE if result.get('serviceUnavailable') else status.HTTP_200_OK)
