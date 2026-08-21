"""
BoloConnect — apps/categories/management/commands/seed_categories.py

Seeds the 10 default service categories defined in SRS §6.3.
Safe to run multiple times — uses get_or_create, never duplicates.

Usage:
  python manage.py seed_categories
  python manage.py seed_categories --clear   # wipe and re-seed (dev only)
"""
from django.core.management.base import BaseCommand
from django.db import transaction

# SRS §6.3 — Default Categories with sub-categories
DEFAULT_CATEGORIES = [
    {
        "title": "Plumbing",
        "description": "Pipe installation, leak repair, drainage, water heaters and sanitation services.",
        "order": 1,
        "children": [
            {"title": "Leak & Pipe Repair",   "description": "Fix burst or leaking pipes.", "order": 1},
            {"title": "Drain Cleaning",        "description": "Unblock and clean drains.", "order": 2},
            {"title": "Water Heater Service",  "description": "Install or repair water heaters.", "order": 3},
            {"title": "Bathroom & Toilet",     "description": "Toilet, shower and bath installation.", "order": 4},
        ],
    },
    {
        "title": "Electrical",
        "description": "Wiring, socket installation, circuit breakers, generators and lighting.",
        "order": 2,
        "children": [
            {"title": "Wiring & Sockets",      "description": "New wiring and socket installation.", "order": 1},
            {"title": "Generator Repair",      "description": "Service and repair generators.", "order": 2},
            {"title": "Lighting Installation", "description": "Indoor and outdoor lighting.", "order": 3},
            {"title": "Circuit Breakers",      "description": "Fuse box and circuit breaker work.", "order": 4},
        ],
    },
    {
        "title": "Carpentry",
        "description": "Custom furniture, door and window fitting, shelving and woodwork.",
        "order": 3,
        "children": [
            {"title": "Furniture & Shelving",  "description": "Custom-built furniture and shelving.", "order": 1},
            {"title": "Door & Window Fitting", "description": "Fit, repair or replace doors and windows.", "order": 2},
            {"title": "Flooring",              "description": "Wood and laminate floor installation.", "order": 3},
        ],
    },
    {
        "title": "Cleaning & Housekeeping",
        "description": "Deep cleaning, regular housekeeping, post-construction and move-in/out cleaning.",
        "order": 4,
        "children": [
            {"title": "Deep Cleaning",         "description": "Full home deep clean service.", "order": 1},
            {"title": "Regular Housekeeping",  "description": "Ongoing weekly or bi-weekly cleaning.", "order": 2},
            {"title": "Post-Construction Clean","description": "Clean up after renovation or construction.", "order": 3},
            {"title": "Office Cleaning",       "description": "Commercial and office cleaning.", "order": 4},
        ],
    },
    {
        "title": "Painting & Decorating",
        "description": "Interior and exterior painting, wallpaper hanging and surface preparation.",
        "order": 5,
        "children": [
            {"title": "Interior Painting",     "description": "Walls, ceilings and trim.", "order": 1},
            {"title": "Exterior Painting",     "description": "Facades, gates and outdoor surfaces.", "order": 2},
            {"title": "Wallpaper & Texturing", "description": "Wallpaper hanging and textured finishes.", "order": 3},
        ],
    },
    {
        "title": "Mechanics & Auto-Repair",
        "description": "Vehicle servicing, diagnostics, tyre fitting and roadside assistance.",
        "order": 6,
        "children": [
            {"title": "Engine & Mechanical",   "description": "Engine diagnostics and mechanical repair.", "order": 1},
            {"title": "Tyre & Wheel Service",  "description": "Tyre fitting, balancing and alignment.", "order": 2},
            {"title": "Electrical & AC",       "description": "Vehicle electrical and air-conditioning.", "order": 3},
            {"title": "Roadside Assistance",   "description": "On-the-spot breakdown help.", "order": 4},
        ],
    },
    {
        "title": "Air Conditioning & HVAC",
        "description": "AC installation, servicing, repair and refrigeration systems.",
        "order": 7,
        "children": [
            {"title": "AC Installation",       "description": "Install new AC units.", "order": 1},
            {"title": "AC Servicing & Repair", "description": "Clean, service and repair AC units.", "order": 2},
            {"title": "Refrigeration",         "description": "Fridge and cold-room repair.", "order": 3},
        ],
    },
    {
        "title": "Security & Locks",
        "description": "Lock fitting, CCTV installation, alarm systems and safe installation.",
        "order": 8,
        "children": [
            {"title": "Lock & Key Service",    "description": "Locks, keys and lockouts.", "order": 1},
            {"title": "CCTV Installation",     "description": "Install and configure CCTV cameras.", "order": 2},
            {"title": "Alarm Systems",         "description": "Burglar and fire alarm installation.", "order": 3},
        ],
    },
    {
        "title": "Landscaping & Gardening",
        "description": "Lawn care, tree trimming, garden design and irrigation systems.",
        "order": 9,
        "children": [
            {"title": "Lawn Mowing & Trimming","description": "Regular lawn care and edging.", "order": 1},
            {"title": "Tree & Hedge Work",     "description": "Pruning, trimming and tree removal.", "order": 2},
            {"title": "Garden Design",         "description": "Landscaping and garden planning.", "order": 3},
        ],
    },
    {
        "title": "General Handyman",
        "description": "Miscellaneous home repairs, assembly, hanging and fixing tasks.",
        "order": 10,
        "children": [
            {"title": "Furniture Assembly",    "description": "Assemble flat-pack and ready-made furniture.", "order": 1},
            {"title": "Wall Mounting & Hanging","description": "Mount TVs, shelves and artwork.", "order": 2},
            {"title": "Tiling & Grouting",     "description": "Tile installation and grout repair.", "order": 3},
            {"title": "General Repairs",       "description": "Miscellaneous household repairs.", "order": 4},
        ],
    },
]


class Command(BaseCommand):
    help = "Seed the 10 default service categories. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all categories before seeding. DEV ONLY.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from categories.models import Category

        if options["clear"]:
            count = Category.objects.all().delete()[0]
            self.stdout.write(self.style.WARNING(f"Cleared {count} category records."))

        created_roots = 0
        created_children = 0
        skipped = 0

        for cat_data in [dict(c) for c in DEFAULT_CATEGORIES]:  # copy to avoid mutating module-level list
            children_data = cat_data.pop("children", [])
            root, root_created = Category.objects.get_or_create(
                slug=self._to_slug(cat_data["title"]),
                defaults={
                    "title":       cat_data["title"],
                    "description": cat_data["description"],
                    "order":       cat_data["order"],
                    "is_active":   True,
                },
            )
            if root_created:
                created_roots += 1
            else:
                skipped += 1

            for child_data in children_data:
                child, child_created = Category.objects.get_or_create(
                    slug=self._to_slug(child_data["title"]),
                    defaults={
                        "title":       child_data["title"],
                        "description": child_data["description"],
                        "order":       child_data["order"],
                        "parent":      root,
                        "is_active":   True,
                    },
                )
                if child_created:
                    created_children += 1
                else:
                    skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created: {created_roots} root categories, "
                f"{created_children} sub-categories. "
                f"Already existed: {skipped}."
            )
        )

    @staticmethod
    def _to_slug(title: str) -> str:
        from django.utils.text import slugify
        return slugify(title)


