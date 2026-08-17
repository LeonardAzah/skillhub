"""
Service layer for dispute operations.

Key responsibilities

1. freeze_escrow_for_dispute - mark EscroAccount as DISPUTED (no financial movement)

2. resolve_dispute - Orchestrate admin resolution:
    REFUND_SEEKER -> payments.refund_escrow(full)
    RELEASE_PROVIDER -> payments.release_escrow
    SPLIT -> payments.refund_escrow(partial)

3. write_audit_log - every action written immutably
4. update_appointment_status - keep Appointment.status in sync with dispute outcomes
"""

import logging

from decimal import Decimal
from datetime import timezone

from django.db import transaction as db_transaction

from .models import DisputeAuditLog, Dispute

from payments.models import EscrowAccount
from payments.services import refund_escrow, release_escrow

from utils.events import EventType
from notifications.publisher import publish_event

logger = logging.getLogger(__name__)


def write_audit(
        dispute: Dispute,
        action: str,
        actor,
        description: str ="",
        diff: dict | None = None,
) -> DisputeAuditLog:
    """Write an immutable audit row. Never raises."""
    try:
        return DisputeAuditLog.objects.create(
            dispute = dispute,
            dispute_id_snapshot = dispute.id,
            action = action,
            actor = actor,
            actor_role = getattr(actor, "role", "") or "",
            description = description,
            diff = diff or {}
        )
    except Exception as exc:
        logging.error("Audit log write failed", extra={"dispute_id": str(dispute.id), "error":str(exc)})

@db_transaction.atomic
def resolve_dispute(
        dispute:Dispute,
        resolution: str,
        resolution_notes:str,
        admin_user,
        split_percent_seeker: int | None = None,    
) -> Dispute:
    """
    Admin resolves the dispute, triggering the correct financial outcome.

    Resolution Outcomes
    REFUND_SEEKER -> Full escrow refunded to seeker
    RELEASE_PROVIDER -> Full escrow released to provider (minus platform fee)
    SPLIT -> split_percent_seeker % to seeker, rest to provider

    Also transitions the appointment status to the appropriate terminal state.
    """

    if dispute.is_terminal:
        raise ValueError(f"Dispute is already in terminal state: {dispute.status}")

    if resolution not in Dispute.Resolution.values:
        raise ValueError(f"Unknown resolution: {resolution}")

    if resolution == Dispute.Resolution.SPLIT:
        if split_percent_seeker is None or not (0 < split_percent_seeker < 100):
            raise ValueError(
                 "split_percent_seeker must be an integer between 1 and 99 for SPLIT resolution."
            )
    appointment = dispute.appointment
    appointment_id = str(appointment.id)

    # Unfreeze the escrow so the operation can proceed
    try: 
        erscrow = EscrowAccount.objects.select_for_update().get(appointment_id=appointment_id)

        if erscrow.status == EscrowAccount.Status.DISPUTED:
            erscrow.status = EscrowAccount.Status.HELD
            erscrow.save(update_fields=["status", "udated_at"])
    except EscrowAccount.DoesNotExist:
        logger.warning("No escrow found during dispute resolution", extra={"appointment_id": appointment_id})

    idempotency_base = f"dispute_resolve:{dispute.id}"

    if resolution == Dispute.Resolution.REFUND_SEEKER:
        refund_escrow(appointment_id=appointment_id, idempotency_key=idempotency_base)
        new_appointment_status = appointment.Status.CONFIRMED #admin resolves in seeker favour
        new_dispute_status = Dispute.Status.RESOLVED_SEEKER

    elif resolution == Dispute.Resolution.RELEASE_PROVIDER:
        release_escrow(appointment_id=appointment_id, idempotency_key=idempotency_base)
        new_appointment_status = appointment.Status.CONFIRMED # admin resolves in providers favour
        new_dispute_status = Dispute.Status.RESOLVED_PROVIDER
    else:
        try:
            erscrow_amount = EscrowAccount.objects.get(appointment_id=appointment_id).amount
        except EscrowAccount.DoesNotExist:
            erscrow_amount = appointment.quoted_price or Decimal("0")

        seeker_amount = (erscrow_amount * Decimal(split_percent_seeker)/100).quantize(Decimal("0.01"))

        refund_escrow(
            appointment_id=appointment_id,
            idempotency_key=idempotency_base,
            partial_amount=seeker_amount,
        )
        new_dispute_status = Dispute.Status.RESOLVED_SEEKER
        new_appointment_status= appointment.Status.CONFIRMED

        if appointment.can_transition_to(new_appointment_status):
            appointment.transition_to(new_appointment_status, actor=admin_user)

        now = timezone.now()
        dispute.status = new_dispute_status
        dispute.resolution = resolution
        dispute.resolution_notes = resolution_notes
        dispute.resolved_by = admin_user
        dispute.resolved_at = now
        dispute.split_percent_seeker = split_percent_seeker

        dispute.save(update_fields=[
            "status", "resolution",
            "resolution_notes", "resolved_by",
            "resolved_at", "split_percent_seeker", "updated_at",
        ])

        write_audit(
            dispute,
            action=DisputeAuditLog.Action.RESOLVED,
            actor=admin_user,
            description=f"Resolution: {resolution}. {resolution_notes}",
             diff={
            "status":     [Dispute.Status.UNDER_REVIEW, new_dispute_status],
            "resolution": [None, resolution],
        },
        )

        publish_event(EventType.DISPUTE_RESOLVED, {
            "dispute_id": str(dispute.id),
            "appointment_id": str(appointment.id),
            "seeker_id": str(appointment.customer.id),
            "provider_id": str(appointment.provider.id),
            "resolution": resolution,
            "resolution_notes": resolution_notes,
            "split_percent_seeker": split_percent_seeker,
        })

        logger.info(
            "Dispute resolved",
            extra={
                "dispute_id": str(dispute.id),
                "resolution": resolution,
                "admin": str(admin_user.id)
            }
        )

        return dispute


