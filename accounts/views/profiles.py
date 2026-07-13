from django.core.cache import cache

from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import User, SeekerProfile, ProviderProfile
from ..serializers import (
    SeekerProfileSerializer,
    UpdateSeekerProfileSerializer,
    ProviderProfileSerializer,
    UpdateProviderProfileSerializer,
    ProviderListQuerySerializer,
)
from ..constants import PROVIDER_LIST_CACHE_KEY, PROVIDER_CACHE_TTL
from ..helper import haversine_km
from ..filters import ProviderFilterSet
from ..cache_utils import get_cache_version
from ..geo import bounding_box

from categories.models import Category, ProviderCategory

from utils.pagination import StandardResultsPagination



# Maps account_type -> (related_name on User, read serializer, write serializer)
PROFILE_CONFIG = {
    User.AccountType.SEEKER: {
        "related_name": "seeker_profile",
        "model": SeekerProfile,
        "read_serializer": SeekerProfileSerializer,
        "write_serializer": UpdateSeekerProfileSerializer,
    },
    User.AccountType.PROVIDER: {
        "related_name": "provider_profile",
        "model": ProviderProfile,
        "read_serializer": ProviderProfileSerializer,
        "write_serializer": UpdateProviderProfileSerializer,
    },
}


class ProfileView(APIView):
    """
    GET   /api/v1/profile/
    PATCH /api/v1/profile/
    """
    permission_classes = [IsAuthenticated]

    def _get_config(self, request):
        """Returns (config, profile) or (None, None) with an error Response set on self._error."""
        self._error = None
        account_type = request.user.account_type

        if not account_type:
            self._error = Response(
                {
                    "success": False,
                    "message": "Please complete onboarding before accessing a profile.",
                    "errors": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
            return None, None

        config = PROFILE_CONFIG.get(account_type)
        if config is None:
            # Defensive: shouldn't happen given the AccountType choices, but guards
            # against future account types being added without a matching entry here.
            self._error = Response(
                {"success": False, "message": "Unsupported account type.", "errors": {}},
                status=status.HTTP_400_BAD_REQUEST,
            )
            return None, None

        try:
            profile = getattr(request.user, config["related_name"])
        except config["model"].DoesNotExist:
            self._error = Response(
                {
                    "success": False,
                    "message": "Profile not found. Please complete onboarding.",
                    "errors": {},
                },
                status=status.HTTP_404_NOT_FOUND,
            )
            return None, None

        return config, profile

    def get(self, request):
        config, profile = self._get_config(request)
        if config is None:
            return self._error

        data = config["read_serializer"](profile).data
        return Response({"success": True, "message": "Profile retrieved.", "data": data})

    def patch(self, request):
        config, profile = self._get_config(request)
        if config is None:
            return self._error

        serializer = config["write_serializer"](profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        data = config["read_serializer"](profile).data
        return Response({"success": True, "message": "Profile updated.", "data": data}, status=status.HTTP_200_OK)


class ProviderPublicProfileView(APIView):
    """
    GET /api/v1/profile/provider/{id}/
    Public read of a *specific* provider by ID
    """
    permission_classes = [AllowAny]

    def get(self, request, provider_id):
        try:
            profile = ProviderProfile.objects.select_related("user").get(id=provider_id)
        except ProviderProfile.DoesNotExist:
            return Response(
                {"success": False, "message": "Provider not found.", "errors": {}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {"success": True, "message": "Provider profile retrieved.", "data": ProviderProfileSerializer(profile).data}
        )
    


class ProvidersView(APIView):
    """
    GET /api/v1/providers
 
    Pipeline (filters stack, applied in this order):
      1. Base:     user.is_verified (KYC) + user.is_active        — always applied
      2. Category: providers linked to category_slug               — optional
      3. Rating:   average_rating >= min_rating                    — optional
      4. Jobs:     total_jobs >= min_jobs                          — optional
      5. Location: within radius_km AND within provider's own
                   service_radius_km                                — optional
 
    Sort:
      - If lat/lng given  -> nearest first (distance always wins over rating)
      - If lat/lng absent -> best rated first (average_rating, then total_jobs)
 
    Query params:
      category_slug  — optional
      lat, lng       — optional, seeker's location (decimal degrees); must be
                       provided together
      radius_km      — only applied when lat/lng given (default: 50, max: 500)
      min_rating     — minimum average_rating (default: 0)
      min_jobs       — minimum total_jobs (default: 0)
      page           — pagination (default: 1)
      page_size      — optional, up to 50 (see StandardResultsPagination)
    """
 
    permission_classes = [AllowAny]
 
    def get(self, request):
        params = ProviderListQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data
 
        cache_key = self._build_cache_key(request, data)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
 
        qs = self._base_queryset()
 
        category_slug = data.get("category_slug")
        if category_slug:
            try:
                category = Category.objects.active().get(slug=category_slug)
            except Category.DoesNotExist:
                return Response(
                    {"error": "Category not found or inactive."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            # .distinct() guards against duplicate rows if a provider is
            # ever linked to the same category more than once.
            qs = qs.filter(providercategory__category=category).distinct()
 
        qs = ProviderFilterSet(request.GET, queryset=qs).qs
 
        distances = {}
        if "lat" in data and "lng" in data:
            ordered, distances = self._sort_by_distance(qs, data)
        else:
            # Deterministic tiebreak (id) so page 2 can't repeat/skip rows
            # when many providers share the same rating and job count.
            ordered = qs.order_by("-average_rating", "-total_jobs", "id")
 
        paginator = StandardResultsPagination()
        page_items = paginator.paginate_queryset(ordered, request, view=self)
 
        results = [self._serialize(p, distances) for p in page_items]
        response = paginator.get_paginated_response(results)
 
        cache.set(cache_key, response.data, PROVIDER_CACHE_TTL)
        return response
 
    # -- helpers --------------------------------------------------------
 
    def _base_queryset(self):
        return ProviderProfile.objects.filter(
            user__is_verified=True,
            user__is_active=True,
        ).select_related("user")
 
    def _sort_by_distance(self, qs, data):
        lat_f, lng_f = data["lat"], data["lng"]
        radius_km = data["radius_km"]
 
        lat_min, lat_max, lng_min, lng_max = bounding_box(lat_f, lng_f, radius_km)
 
        # Cheap, indexable DB-level pre-filter first. Only the (much
        # smaller) candidates left after this get the exact haversine
        # calculation in Python. This is the fix for the original code
        # pulling the *entire* filtered table into memory on every request.
        candidates = qs.filter(
            location_lat__isnull=False,
            location_lng__isnull=False,
            location_lat__range=(lat_min, lat_max),
            location_lng__range=(lng_min, lng_max),
        )
 
        distances = {}
        nearby = []
        for p in candidates:
            d = haversine_km(lat_f, lng_f, float(p.location_lat), float(p.location_lng))
            if d <= radius_km and d <= float(p.service_radius_km):
                distances[p.id] = d
                nearby.append(p)
 
        nearby.sort(key=lambda p: (distances[p.id], p.id))
        return nearby, distances
 
    def _serialize(self, p, distances):
        return {
            "id": str(p.id),
            "full_name": p.full_name or "",
            "bio": p.bio,
            "hourly_rate": str(p.hourly_rate) if p.hourly_rate else None,
            "experience_years": p.experience_years,
            "average_rating": str(p.average_rating),
            "total_jobs": p.total_jobs,
            "is_kyc_verified": p.user.is_verified,
            "verified_badge": p.verified_badge,
            "service_radius_km": p.service_radius_km,
            "location_address": p.location_address,
            "distance_km": round(distances[p.id], 2) if p.id in distances else None,
        }
 
    def _build_cache_key(self, request, data):
        # Rounding lat/lng means nearby seekers land on the *same* cache
        # key instead of every unique GPS reading producing a key that's
        # (statistically) never requested again -- this was the main
        # reason the original cache almost never hit for location queries.
        parts = [f"v{get_cache_version()}"]
        if "lat" in data and "lng" in data:
            parts.append(f"lat={round(data['lat'], 2)}")
            parts.append(f"lng={round(data['lng'], 2)}")
            parts.append(f"radius={round(data['radius_km'])}")
        parts.append(f"category={data.get('category_slug', '')}")
        parts.append(f"min_rating={data.get('min_rating', 0)}")
        parts.append(f"min_jobs={data.get('min_jobs', 0)}")
        parts.append(f"page={request.query_params.get('page', 1)}")
        parts.append(f"page_size={request.query_params.get('page_size', '')}")
        return "providers_list:" + ":".join(parts)

# class ProvidersView(APIView):
#     """
#     GET /api/v1/providers

#     Pipeline (filters stack, applied in this order):
#       1. Base:     user.is_verified (KYC) + user.is_active        — always applied
#       2. Category: providers linked to category_slug               — optional
#       3. Rating:   average_rating >= min_rating                    — optional
#       4. Location: within radius_km AND within provider's own
#                    service_radius_km                                — optional

#     Sort:
#       - If lat/lng given  -> nearest first (distance always wins over rating)
#       - If lat/lng absent -> best rated first (average_rating, then total_jobs)

#     Query params:
#       category_slug  — optional
#       lat, lng       — optional, seeker's location (decimal degrees)
#       radius_km      — only applied when lat/lng given (default: 50)
#       min_rating     — minimum average_rating (default: 0)
#       page           — pagination (default: 1)
#       page_size      — optional, up to 50 (see StandardResultsPagination)
#     """
#     permission_classes = [AllowAny]

#     def get(self, request):
#         cache_key = (
#             f"{PROVIDER_LIST_CACHE_KEY}:"
#             f"{request.GET.urlencode()}"
#         )

#         cached = cache.get(cache_key)
#         if cached is not None:
#             return Response(cached)

#         # 1. Base filter — KYC verified + active only
#         qs = ProviderProfile.objects.filter(
#             user__is_verified=True,
#             user__is_active=True,
#         ).select_related("user")

#         # 2. Category filter
#         category_slug = request.query_params.get("category_slug")
#         if category_slug:
#             try:
#                 category = Category.objects.active().get(slug=category_slug)
#             except Category.DoesNotExist:
#                 return Response(
#                     {"error": "Category not found or inactive."},
#                     status=status.HTTP_404_NOT_FOUND,
#                 )
#             provider_ids = ProviderCategory.objects.filter(
#                 category=category
#             ).values_list("provider_id", flat=True)
#             qs = qs.filter(id__in=provider_ids)

#         # 3. Rating filter
#         min_rating = request.query_params.get("min_rating")
#         if min_rating:
#             try:
#                 qs = qs.filter(average_rating__gte=float(min_rating))
#             except ValueError:
#                 pass

#         # 4. Location filter + sort
#         lat = request.query_params.get("lat")
#         lng = request.query_params.get("lng")
#         distances = {}  # provider_id -> distance_km, populated only when lat/lng given

#         if lat and lng:
#             try:
#                 lat_f, lng_f = float(lat), float(lng)
#             except ValueError:
#                 return Response(
#                     {"error": "lat and lng must be decimal numbers."},
#                     status=status.HTTP_400_BAD_REQUEST,
#                 )

#             try:
#                 radius_km = float(request.query_params.get("radius_km", 50))
#             except ValueError:
#                 radius_km = 50

#             # NOTE: evaluates the queryset into memory to compute distance in
#             # Python. Fine at current scale; once provider counts grow, switch
#             # location_lat/lng to a PostGIS PointField and do this in the DB
#             # with ST_DWithin + Distance (or pre-filter with a bounding box
#             # before running haversine on the remainder).
#             nearby = []
#             for p in qs.filter(location_lat__isnull=False, location_lng__isnull=False):
#                 d = haversine_km(lat_f, lng_f, float(p.location_lat), float(p.location_lng))
#                 if d <= radius_km and d <= p.service_radius_km:
#                     distances[p.id] = d
#                     nearby.append(p)

#             # Distance always wins when location is provided
#             nearby.sort(key=lambda p: distances[p.id])
#             ordered = nearby
#         else:
#             # No location given — fall back to rating-based ranking
#             ordered = list(qs.order_by("-average_rating", "-total_jobs"))

#         # Paginate via shared pagination util
#         page_items = self.paginate_queryset(ordered, request, view=self)

#         results = [
#             {
#                 "id": str(p.id),
#                 "full_name": p.full_name or "",
#                 "bio": p.bio,
#                 "hourly_rate": str(p.hourly_rate) if p.hourly_rate else None,
#                 "experience_years": p.experience_years,
#                 "average_rating": str(p.average_rating),
#                 "total_jobs": p.total_jobs,
#                 "is_kyc_verified": p.user.is_verified,
#                 "verified_badge": p.verified_badge,
#                 "service_radius_km": p.service_radius_km,
#                 "location_address": p.location_address,
#                 "distance_km": round(distances[p.id], 2) if p.id in distances else None,
#             }
#             for p in page_items
#         ]
#         response = self.self.get_paginated_respons(results)

#         cache.set(
#             cache_key, response.data, None
#         )

#         return response