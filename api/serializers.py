from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    UserProfile, Concours, Resource, Submission, Quiz,
    QuizAttempt, ForumTopic, ForumReply, CalendarEvent, OralSession,
    Enrollment, LearningContent, UserProgress, Activity, Notification,
    TutorMessage, TutorAppointment, Subscription, CandidateWorkSubmission
)

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = [
            'role', 'status', 'phone', 'target_concours', 'address', 'diploma',
            'university', 'specialty', 'bio', 'avatar_url', 'interests', 'is_premium',
            'two_factor_enabled', 'email_notifications', 'sms_notifications',
            'push_notifications',
        ]

class UserSerializer(serializers.ModelSerializer):
    role = serializers.CharField(source='profile.role', read_only=True)
    status = serializers.CharField(source='profile.status', read_only=True)
    phone = serializers.CharField(source='profile.phone', read_only=True)
    target_concours = serializers.CharField(source='profile.target_concours', read_only=True)
    profile = UserProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'role', 'status', 'phone', 'target_concours', 'profile', 'date_joined']

class ConcoursSerializer(serializers.ModelSerializer):
    candidates_count = serializers.IntegerField(source='enrollments.count', read_only=True)
    class Meta:
        model = Concours
        fields = ['id', 'id_code', 'title', 'category', 'session', 'modules', 'description', 'candidates_count',
                  'requirements', 'subjects', 'career_paths', 'exam_date', 'registration_deadline',
                  'source_name', 'source_url', 'verified_at', 'active', 'created_at']

class ResourceSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.get_full_name', read_only=True)

    class Meta:
        model = Resource
        fields = ['id', 'title', 'concourse', 'concourse_name', 'type', 'file_name', 'url', 'metadata', 'author', 'author_name', 'status', 'created_at']

class SubmissionSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.get_full_name', read_only=True)
    author_email = serializers.CharField(source='author.email', read_only=True)

    class Meta:
        model = Submission
        fields = ['id', 'title', 'type', 'body', 'author', 'author_name', 'author_email', 'status', 'created_at']

class QuizSerializer(serializers.ModelSerializer):
    class Meta:
        model = Quiz
        fields = ['id', 'title', 'concourse_target', 'questions_data', 'author', 'created_at']

class QuizAttemptSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = QuizAttempt
        fields = ['id', 'user', 'user_name', 'username', 'quiz', 'quiz_title', 'score', 'total', 'percentage', 'created_at']

class ForumReplySerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_avatar = serializers.CharField(source='author.profile.avatar_url', read_only=True, default='')
    author_role = serializers.CharField(source='author.profile.role', read_only=True, default='candidat')

    def get_author_name(self, obj):
        return obj.author.get_full_name() or obj.author.username

    class Meta:
        model = ForumReply
        fields = ['id', 'topic', 'author', 'author_name', 'author_avatar', 'author_role', 'content', 'created_at']

class ForumTopicSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_avatar = serializers.CharField(source='author.profile.avatar_url', read_only=True, default='')
    author_role = serializers.CharField(source='author.profile.role', read_only=True, default='candidat')
    replies_count = serializers.IntegerField(source='replies.count', read_only=True)
    replies = ForumReplySerializer(many=True, read_only=True)
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)

    def get_author_name(self, obj):
        return obj.author.get_full_name() or obj.author.username

    class Meta:
        model = ForumTopic
        fields = ['id', 'title', 'category', 'author', 'author_name', 'author_avatar', 'author_role', 'content', 'views_count', 'is_pinned', 'created_at', 'replies_count', 'likes_count', 'replies']

class CalendarEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CalendarEvent
        fields = ['id', 'user', 'title', 'concourse_name', 'event_type', 'event_date', 'event_time', 'completed', 'description']

class OralSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = OralSession
        fields = ['id', 'user', 'concourse_name', 'question', 'transcript', 'duration', 'evaluation_json', 'created_at']


class EnrollmentSerializer(serializers.ModelSerializer):
    concourse_detail = ConcoursSerializer(source='concourse', read_only=True)

    class Meta:
        model = Enrollment
        fields = ['id', 'concourse', 'concourse_detail', 'created_at']


class LearningContentSerializer(serializers.ModelSerializer):
    concourse_code = serializers.CharField(source='concourse.id_code', read_only=True)
    concourse_title = serializers.CharField(source='concourse.title', read_only=True)
    author_name = serializers.CharField(source='author.get_full_name', read_only=True)

    class Meta:
        model = LearningContent
        fields = ['id', 'kind', 'slug', 'title', 'concourse', 'concourse_code', 'concourse_title', 'data',
                  'author', 'author_name', 'status', 'is_private', 'source_name', 'source_url', 'verified_at', 'created_at', 'updated_at']


class UserProgressSerializer(serializers.ModelSerializer):
    content_kind = serializers.CharField(source='content.kind', read_only=True)

    class Meta:
        model = UserProgress
        fields = ['id', 'content', 'content_kind', 'progress', 'completed', 'score', 'updated_at']


class ActivitySerializer(serializers.ModelSerializer):
    concourse_code = serializers.CharField(source='concourse.id_code', read_only=True)
    concourse_title = serializers.CharField(source='concourse.title', read_only=True)

    class Meta:
        model = Activity
        fields = ['id', 'activity_type', 'title', 'concourse', 'concourse_code', 'concourse_title',
                  'score', 'total', 'duration_seconds', 'details', 'created_at']


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'message', 'type', 'read', 'action_url', 'created_at']


class TutorMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    recipient_name = serializers.SerializerMethodField()

    def get_sender_name(self, obj):
        return obj.sender.get_full_name() or obj.sender.username or obj.sender.email

    def get_recipient_name(self, obj):
        return obj.recipient.get_full_name() or obj.recipient.username or obj.recipient.email

    class Meta:
        model = TutorMessage
        fields = ['id', 'sender', 'sender_name', 'recipient', 'recipient_name', 'text', 'attachment_url', 'read', 'created_at']


class TutorAppointmentSerializer(serializers.ModelSerializer):
    candidate_name = serializers.SerializerMethodField()
    candidate_email = serializers.CharField(source='candidate.email', read_only=True)
    tutor_name = serializers.SerializerMethodField()

    def get_candidate_name(self, obj):
        return obj.candidate.get_full_name() or obj.candidate.username or obj.candidate.email

    def get_tutor_name(self, obj):
        return obj.tutor.get_full_name() or obj.tutor.username or obj.tutor.email

    class Meta:
        model = TutorAppointment
        fields = ['id', 'candidate', 'candidate_name', 'candidate_email', 'tutor', 'tutor_name', 'scheduled_at', 'topic', 'status', 'meeting_url', 'created_at']


class SubscriptionSerializer(serializers.ModelSerializer):
    plan_title = serializers.CharField(source='plan.title', read_only=True)
    plan_data = serializers.JSONField(source='plan.data', read_only=True)

    class Meta:
        model = Subscription
        fields = ['id', 'plan', 'plan_title', 'plan_data', 'status', 'payment_method', 'provider_reference', 'created_at', 'updated_at']


class CandidateWorkSubmissionSerializer(serializers.ModelSerializer):
    candidate_name = serializers.SerializerMethodField()
    candidate_email = serializers.CharField(source='candidate.email', read_only=True)
    teacher_name = serializers.SerializerMethodField()
    concourse_title = serializers.CharField(source='concourse.title', read_only=True)

    def get_candidate_name(self, obj):
        return obj.candidate.get_full_name() or obj.candidate.username or obj.candidate.email

    def get_teacher_name(self, obj):
        if not obj.teacher:
            return ''
        return obj.teacher.get_full_name() or obj.teacher.username or obj.teacher.email

    class Meta:
        model = CandidateWorkSubmission
        fields = [
            'id', 'candidate', 'candidate_name', 'candidate_email', 'teacher', 'teacher_name',
            'concourse', 'concourse_title', 'resource', 'title', 'question', 'answer',
            'local_evaluation', 'teacher_score', 'teacher_feedback', 'status', 'created_at', 'updated_at',
        ]
