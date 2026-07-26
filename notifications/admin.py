from django.contrib import admin
from .models import Notification, EmailLog

# Register your models here.
admin.site.register(Notification)
admin.site.register(EmailLog)