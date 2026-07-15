from django.contrib import admin
from .models import Category, ProviderCategory

# Register your models here.
admin.site.register(Category)
admin.site.register(ProviderCategory)