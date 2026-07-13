from django.urls import path

from .views import (
    AdminCategoryActivateView,
    AdminCategoryCreateView,
    AdminCategoryDeactivateView,
    AdminCategoryListView,
    AdminCategoryUpdateView,
    CategoryDetailView,
    CategoryListView,
    ProviderCategoryListView,
    ProviderCategoryUpdateView,
)


urlpatterns = [
    # Public
    path("", CategoryListView.as_view(), name="category-list"),
    path("<slug:slug>", CategoryDetailView.as_view(), name="category-detail"),

    # Provider
    path(
        "profile/provider/categories",
        ProviderCategoryListView.as_view(),
        name="provider-category-list",
    ),
    path(
        "profile/provider/categories/update",
        ProviderCategoryUpdateView.as_view(),
        name="provider-category-update",
    ),

    # Admin
    path(
        "admin/categories",
        AdminCategoryListView.as_view(),
        name="admin-category-list",
    ),
    path(
        "admin/categories/create",
        AdminCategoryCreateView.as_view(),
        name="admin-category-create",
    ),
    path(
        "admin/categories/<slug:slug>",
        AdminCategoryUpdateView.as_view(),
        name="admin-category-update",
    ),
    path(
        "admin/categories/<slug:slug>/delete",
        AdminCategoryDeactivateView.as_view(),
        name="admin-category-deactivate",
    ),
    path(
        "admin/categories/<slug:slug>/activate",
        AdminCategoryActivateView.as_view(),
        name="admin-category-activate",
    ),
]