from django.urls import path
from . import views

urlpatterns = [
    # Health check
    path('health/', views.health_check, name='health_check'),

    # Authentication
    path('auth/login/', views.login_view, name='login'),
    path('auth/register/', views.register_view, name='register'),
    path('auth/me/', views.me_view, name='me'),
    path('auth/logout/', views.logout_view, name='logout'),
    path('auth/change-password/', views.change_password_view, name='change_password'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/avatar/', views.profile_avatar_upload, name='profile_avatar_upload'),
    path('profile/avatar/<str:filename>', views.profile_avatar_file, name='profile_avatar_file'),

    # Concours CRUD
    path('concours/', views.concours_list_create, name='concours_list_create'),
    path('concours/<int:pk>/', views.concours_detail, name='concours_detail'),

    # Resources
    path('resources/', views.resource_list_create, name='resource_list_create'),
    path('resources/<int:pk>/', views.resource_detail, name='resource_detail'),

    # Submissions & Moderation
    path('submissions/', views.submission_list_create, name='submission_list_create'),
    path('submissions/<int:pk>/moderate/', views.submission_moderate, name='submission_moderate'),

    # Forum Compartment
    path('forum/', views.forum_topics_list_create, name='forum_topics_list_create'),
    path('forum/<int:topic_pk>/reply/', views.forum_reply_create, name='forum_reply_create'),
    path('forum/<int:topic_pk>/like/', views.forum_like_toggle, name='forum_like_toggle'),

    # Leaderboard & Quiz Attempts
    path('leaderboard/', views.leaderboard_list_create_attempt, name='leaderboard_list_create_attempt'),

    # Calendar Events
    path('calendar/', views.calendar_events_list_create, name='calendar_events_list_create'),
    path('calendar/<int:pk>/', views.calendar_event_detail, name='calendar_event_detail'),

    # Admin Management
    path('admin/users/', views.admin_users_list_create, name='admin_users_list_create'),
    path('admin/users/<int:pk>/', views.admin_user_update, name='admin_user_update'),
    path('admin/overview/', views.admin_overview, name='admin_overview'),
    path('teacher/overview/', views.teacher_overview, name='teacher_overview'),

    # Persistent learning and user data
    path('content/', views.content_list_create, name='content_list_create'),
    path('content/<int:pk>/', views.content_detail, name='content_detail'),
    path('enrollments/', views.enrollments_view, name='enrollments'),
    path('progress/', views.progress_view, name='progress'),
    path('activities/', views.activities_view, name='activities'),
    path('activities/summary/', views.activity_summary, name='activity_summary'),
    path('study-sessions/', views.study_sessions_view, name='study_sessions'),
    path('notifications/', views.notifications_view, name='notifications'),
    path('tutors/', views.tutors_view, name='tutors'),
    path('tutor-messages/', views.tutor_messages_view, name='tutor_messages'),
    path('appointments/', views.appointments_view, name='appointments'),
    path('subscriptions/', views.subscriptions_view, name='subscriptions'),
    path('subscriptions/verify/', views.verify_subscription_view, name='verify_subscription'),
    path('work-submissions/', views.work_submissions_view, name='work_submissions'),

    # Gemini AI Services
    path('gemini/jury-eval/', views.gemini_jury_eval, name='gemini_jury_eval'),
    path('gemini/tutor-chat/', views.gemini_tutor_chat, name='gemini_tutor_chat'),
    path('gemini/generate-quiz/', views.gemini_generate_quiz, name='gemini_generate_quiz'),
    path('gemini/generate-material/', views.gemini_generate_material, name='gemini_generate_material'),
    path('gemini/orientation-chat/', views.gemini_orientation_chat, name='gemini_orientation_chat'),
    path('gemini/grade-answer/', views.gemini_grade_answer, name='gemini_grade_answer'),
    path('documents/extract/', views.extract_document_text, name='extract_document_text'),
]
