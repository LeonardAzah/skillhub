from django.contrib import admin
from .models import User, ProviderProfile, SeekerProfile

# Register your models here.
admin.site.register(User)
admin.site.register(ProviderProfile)
admin.site.register(SeekerProfile)