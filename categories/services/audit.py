from ..models import CategoryAuditLog, Category


def write_audit_log(
    category: Category,
    action: str,
    actor,
    diff: dict | None = None,
):
    CategoryAuditLog.objects.create(
        category=category,
        category_slug=category.slug,
        action=action,
        actor=actor,
        diff=diff or {},
    )

def build_diff(old_data: dict, new_data: dict) -> dict:
    """Return {field: [old_value, new_value]} for changed fields."""
    diff = {}
    for key in set(old_data) | set(new_data):
        old_val = old_data.get(key)
        new_val = new_data.get(key)
        if str(old_val) != str(new_val):
            diff[key] = [old_val, new_val]
    return diff