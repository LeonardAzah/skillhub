from django.urls import path

from .views import (
    AdminCategoryActivateView,
    # AdminCategoryCreateView,
    # AdminCategoryDeactivateView,
    AdminCategoryListView,
    # AdminCategoryUpdateView,
    CategoryDetailView,
    # CategoryListView,
    CategoryListCreateView,
    ProviderCategoryListView,
    ProviderCategoryUpdateView,
    CategoryListCreateView,
)


urlpatterns = [
 path(
        "/all",
        AdminCategoryListView.as_view(),
        name="admin-category-list",
    ),
    path("", CategoryListCreateView.as_view(), name="category-list"),
    # Provider
    path(
        "/providers",
        ProviderCategoryListView.as_view(),
        name="provider-category-list",
    ),

   path("/<slug:slug>", CategoryDetailView.as_view(), name="category-detail"),

    
    path(
        "/providers/categories",
        ProviderCategoryUpdateView.as_view(),
        name="provider-category-update",
    ),

    path(
        "/<slug:slug>/activate",
        AdminCategoryActivateView.as_view(),
        name="admin-category-activate",
    ),
]