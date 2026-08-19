from django.db import models
from django.contrib.auth.models import User
import secrets

class UserProfile(models.Model):
    ROLE_CHOICES = (
        ('candidat', 'Candidat'),
        ('enseignant', 'Enseignant'),
        ('admin', 'Administrateur'),
    )
    STATUS_CHOICES = (
        ('active', 'Actif'),
        ('suspended', 'Suspendu'),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='candidat')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    phone = models.CharField(max_length=30, blank=True, null=True)
    target_concours = models.CharField(max_length=100, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True)
    diploma = models.CharField(max_length=255, blank=True)
    university = models.CharField(max_length=255, blank=True)
    specialty = models.CharField(max_length=255, blank=True)
    bio = models.TextField(blank=True)
    avatar_url = models.URLField(blank=True)
    interests = models.JSONField(default=list, blank=True)
    is_premium = models.BooleanField(default=False)
    two_factor_enabled = models.BooleanField(default=False)
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    push_notifications = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} ({self.role})"

class Concours(models.Model):
    id_code = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    session = models.CharField(max_length=50, default='2026')
    modules = models.JSONField(default=list)
    description = models.TextField(blank=True, null=True)
    candidates_count = models.IntegerField(default=0)
    requirements = models.JSONField(default=list, blank=True)
    subjects = models.JSONField(default=list, blank=True)
    career_paths = models.JSONField(default=list, blank=True)
    exam_date = models.DateField(blank=True, null=True)
    registration_deadline = models.DateField(blank=True, null=True)
    source_name = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(blank=True)
    verified_at = models.DateTimeField(blank=True, null=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.session})"

class Resource(models.Model):
    TYPE_CHOICES = (
        ('pdf', 'PDF / Epreuve'),
        ('video', 'Vidéo'),
        ('fiche', 'Fiche de révision'),
    )
    STATUS_CHOICES = (
        ('published', 'Publié'),
        ('pending', 'En attente'),
    )
    title = models.CharField(max_length=255)
    concourse = models.ForeignKey(Concours, on_delete=models.CASCADE, related_name='resources', null=True, blank=True)
    concourse_name = models.CharField(max_length=100, blank=True, null=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='pdf')
    file_name = models.CharField(max_length=255)
    url = models.URLField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='published')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class Submission(models.Model):
    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
    )
    title = models.CharField(max_length=255)
    type = models.CharField(max_length=50, default='annale')
    body = models.TextField()
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='submissions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} - {self.status}"

class Quiz(models.Model):
    title = models.CharField(max_length=255)
    concourse_target = models.CharField(max_length=100, blank=True, null=True)
    questions_data = models.JSONField(default=list)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class QuizAttempt(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quiz_attempts')
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='attempts', null=True, blank=True)
    quiz_title = models.CharField(max_length=255)
    score = models.IntegerField(default=0)
    total = models.IntegerField(default=10)
    percentage = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.quiz_title} ({self.score}/{self.total})"

class ForumTopic(models.Model):
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=100, default='Général')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='forum_topics')
    content = models.TextField()
    views_count = models.IntegerField(default=0)
    is_pinned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class ForumReply(models.Model):
    topic = models.ForeignKey(ForumTopic, on_delete=models.CASCADE, related_name='replies')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='forum_replies')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reply to {self.topic.title} by {self.author.username}"


class ForumLike(models.Model):
    topic = models.ForeignKey(ForumTopic, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='forum_likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['topic', 'user'], name='unique_forum_like')]

class CalendarEvent(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calendar_events', null=True, blank=True)
    title = models.CharField(max_length=255)
    concourse_name = models.CharField(max_length=100)
    event_type = models.CharField(max_length=50, default='ecrit') # inscription, ecrit, oral, resultats
    event_date = models.DateField()
    event_time = models.TimeField(blank=True, null=True)
    completed = models.BooleanField(default=False)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.title} ({self.event_date})"

class OralSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='oral_sessions', null=True, blank=True)
    concourse_name = models.CharField(max_length=100)
    question = models.TextField()
    transcript = models.TextField()
    duration = models.CharField(max_length=20, default='01:30')
    evaluation_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Oral {self.concourse_name} - {self.created_at.strftime('%Y-%m-%d')}"


class ApiToken(models.Model):
    key = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_tokens')
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(blank=True, null=True)

    @classmethod
    def issue(cls, user):
        cls.objects.filter(user=user).delete()
        return cls.objects.create(user=user, key=secrets.token_urlsafe(40))


class Enrollment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enrollments')
    concourse = models.ForeignKey(Concours, on_delete=models.CASCADE, related_name='enrollments')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'concourse'], name='unique_user_concourse')]


class LearningContent(models.Model):
    KIND_CHOICES = (
        ('course', 'Cours'),
        ('quiz_bank', 'Banque de quiz'),
        ('flashcard', 'Flashcard'),
        ('oral_bank', 'Banque de questions orales'),
        ('exam', 'Examen blanc'),
        ('checkpoint', 'Parcours de progression'),
        ('subscription_plan', 'Formule abonnement'),
        ('wellbeing', 'Ressource bien-être'),
    )
    STATUS_CHOICES = (('draft', 'Brouillon'), ('published', 'Publié'), ('archived', 'Archivé'))
    kind = models.CharField(max_length=40, choices=KIND_CHOICES, db_index=True)
    slug = models.SlugField(max_length=160, unique=True)
    title = models.CharField(max_length=255)
    concourse = models.ForeignKey(Concours, on_delete=models.CASCADE, related_name='learning_contents', null=True, blank=True)
    data = models.JSONField(default=dict)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='learning_contents', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    is_private = models.BooleanField(default=False)
    source_name = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(blank=True)
    verified_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class UserProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='content_progress')
    content = models.ForeignKey(LearningContent, on_delete=models.CASCADE, related_name='user_progress')
    progress = models.JSONField(default=dict)
    completed = models.BooleanField(default=False)
    score = models.FloatField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'content'], name='unique_user_content_progress')]


class Activity(models.Model):
    ACTIVITY_CHOICES = (
        ('quiz', 'Quiz'), ('oral', 'Oral'), ('exam', 'Examen'),
        ('course', 'Cours'), ('flashcard', 'Flashcard'), ('wellbeing', 'Bien-être'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    activity_type = models.CharField(max_length=30, choices=ACTIVITY_CHOICES)
    title = models.CharField(max_length=255)
    concourse = models.ForeignKey(Concours, on_delete=models.SET_NULL, related_name='activities', null=True, blank=True)
    score = models.FloatField(blank=True, null=True)
    total = models.FloatField(blank=True, null=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class StudySession(models.Model):
    """Server-side record of time while the learning workspace is genuinely active."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='study_sessions')
    session_key = models.CharField(max_length=64)
    started_at = models.DateTimeField(auto_now_add=True)
    last_heartbeat = models.DateTimeField(default=models.functions.Now)
    ended_at = models.DateTimeField(blank=True, null=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'session_key'], name='unique_user_study_session')]


class Notification(models.Model):
    TYPE_CHOICES = (('reminder', 'Rappel'), ('exam', 'Concours'), ('tutor', 'Tuteur'), ('system', 'Système'), ('badge', 'Badge'))
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='system')
    read = models.BooleanField(default=False)
    action_url = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class TutorMessage(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_tutor_messages')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_tutor_messages')
    text = models.TextField()
    attachment_url = models.URLField(blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class TutorAppointment(models.Model):
    STATUS_CHOICES = (
        ('pending', 'En attente'), ('confirmed', 'Confirmé'), ('rejected', 'Refusé'),
        ('cancelled', 'Annulé'), ('completed', 'Terminé'),
    )
    candidate = models.ForeignKey(User, on_delete=models.CASCADE, related_name='candidate_appointments')
    tutor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tutor_appointments')
    scheduled_at = models.DateTimeField()
    topic = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    meeting_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Subscription(models.Model):
    STATUS_CHOICES = (('pending', 'En attente'), ('active', 'Actif'), ('cancelled', 'Annulé'), ('failed', 'Échec'))
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(LearningContent, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=30, blank=True)
    provider_reference = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CandidateWorkSubmission(models.Model):
    STATUS_CHOICES = (
        ('submitted', 'Soumis'),
        ('reviewed', 'Corrigé'),
        ('returned', 'À reprendre'),
    )
    candidate = models.ForeignKey(User, on_delete=models.CASCADE, related_name='candidate_work_submissions')
    teacher = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='teacher_work_submissions', null=True, blank=True)
    concourse = models.ForeignKey(Concours, on_delete=models.SET_NULL, related_name='work_submissions', null=True, blank=True)
    resource = models.ForeignKey(Resource, on_delete=models.SET_NULL, related_name='work_submissions', null=True, blank=True)
    title = models.CharField(max_length=255)
    question = models.TextField()
    answer = models.TextField()
    local_evaluation = models.JSONField(default=dict, blank=True)
    teacher_score = models.FloatField(null=True, blank=True)
    teacher_feedback = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.candidate.username} — {self.title}"
