import logging

from django.db.models import Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView, GenericAPIView


from .models import Dispute, DisputeEvidence, DisputeAuditLog
from .filters import DisputeFilter
from .serializers import (
    DisputeSerializer,
    SubmitStatementSerializer,
    UploadEvidenceSerializer,
    MarkUnderReviewSerializer,
    ResolveSerializer,
    CloserSerializer,
)
from .services import write_audit, resolve_dispute
from utils.exceptions import error_response
from utils.permissions import IsAdmin

from .help import _get_dispute_qs, _get_dispute_or_404, _dispute_payload

from accounts.models import User
from notifications.publisher import publish_event
from utils.events import EventType
logger = logging.getLogger(__name__)

class IsDisputeParty(BasePermission):
    """Allow the customer, the provider, or staff/admin."""

    def has_object_permission(self, request, view, obj: Dispute) -> bool:
        user = request.user
        return (
            obj.appointment.customer.user_id == user.id
            or obj.appointment.provider.user_id == user.id
            or user.role == User.Role.ADMIN
            or user.is_staff
        )


class DisputeListView(ListAPIView):
    """
    GET /api/v1/disputes/
    Returns disputes where the requesting user is a party
    """
    serializer_class = DisputeSerializer
    permission_classes = [IsAuthenticated] 
    filter_backends = [DjangoFilterBackend]
    filterset_class = DisputeFilter

    def get_queryset(self):
        user = self.request.user
        qs = _get_dispute_qs()

        if user.is_staff or user.role == User.Role.ADMIN:
            return qs

        return qs.filter(
            Q(appointment__customer__user=user) | Q(appointment__provider__user=user)
        ).distinct()
    
class DisputeDetailView(GenericAPIView):
    """
    GET /api/v1/disputes/{id}/
    Both parties and admins may view. admin_notes stripped for non-admins.
    """
    serializer_class = DisputeSerializer
    permission_classes = [IsAuthenticated, IsDisputeParty]

    def get_object(self):
        dispute, err = _get_dispute_or_404(self.kwargs["pk"])
        if err:
            self._error = err
            return None
        self.check_object_permissions(self.request, dispute)
        return dispute

    def get(self, request, pk):
        dispute = self.get_object()
        if dispute is None:
            return self._error

        data = self.get_serializer(dispute).data
        if not request.user.is_staff:
            data.pop("admin_notes", None)

        return Response(
            {
                "success": True,
                "message": "Successfully retrieved dispute detail",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )
class AdminDisputeDetailView(GenericAPIView):
    """
    GET /api/v1/admin/disputes/{id}/
    Full detail including admin_notes and complete audit log.
    """
    serializer_class = DisputeSerializer
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, pk):
        dispute, err = _get_dispute_or_404(pk)
        if err:
            return err

        data = self.get_serializer(dispute).data

        logs = (
            DisputeAuditLog.objects.filter(dispute_id_snapshot=dispute.id)
            .select_related("actor")
            .order_by("timestamp")
        )
        data["audit_logs"] = [
            {
                "action": log.action,
                "actor": log.actor.email if log.actor else "system",
                "actor_role": log.actor_role,
                "description": log.description,
                "diff": log.diff,
                "timestamp": log.timestamp.isoformat(),
            }
            for log in logs
        ]

        return Response(
            {
                "success": True,
                "message": "Successfully retrieved dispute detail",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )

class SubmitStatementView(APIView):
    """
    POST /api/v1/disputes/{id}/statement
    Provider submits counter-statement within 48Hours.
    """
    permission_classes=[IsAuthenticated, IsDisputeParty]

    def post(self, request, pk):
        dispute, err = _get_dispute_or_404(pk)
        if err:
            return err
        
        user = request.user
        serializer = SubmitStatementSerializer(
            data=request.data,
            context={"dispute":dispute, "request": request},
        )
        serializer.is_valid(raise_exception=True)
        statement = serializer.validated_data["statement"]

        if user.role == "provider":
            dispute.provider_statement = statement
            dispute.provider_statement_at = timezone.now()
            dispute.save(update_fields=["provider_statement", "provider_statement_at", "updated_at"])
            audit_action = DisputeAuditLog.Action.STATEMENT_PROVIDER
        else:
            # Seeker updates their original statement
            dispute.seeker_statement = statement
            dispute.save(update_fields=["seeker_statement", "updated_at"])
            audit_action = DisputeAuditLog.Action.STATEMENT_SEEKER

        write_audit(
            dispute,
            action=audit_action,
            actor=user,
            description=f"{user.role.capitalize()} submitted statement"
        )

        publish_event(EventType.DISPUTE_STATEMENT_ADDED, {
            **_dispute_payload(dispute),
            "submitted_by":str(user.id),
            "role": user.role,
        })

        data = DisputeSerializer(dispute).data
        if not User.is_staff:
            data.pop("admin_notes", None)

        return Response(
            {
                "success": True,
                "message":"Sucessfully submitted dispute statement.",
                "data": data
            },
            status=status.HTTP_201_CREATED
        )

class UploadEvidenceView(APIView):
    """
    POST /api/v1/disputes/{id}/evidence
    To upload evidence
    File must be pre-uploaded to s3 or cloudinary
    """

    permission_classes = [IsAuthenticated, IsDisputeParty]

    def post(self, request, pk):
        dispute, err = _get_dispute_or_404(pk)

        if err:
            return err
        user = request.user
        serializer = UploadEvidenceSerializer(data=request.data, context={"dispute": dispute})

        serializer.is_valid(raise_exception=True)
        validated_value = serializer.validated_data

        evidence = DisputeEvidence.objects.create(
            dispute = dispute,
            uploaded_by = user,
            file_url = validated_value["file_url"],
            file_type=validated_value["file_type"],
            description = validated_value.get("descripton", ""),
        )

        write_audit(
            dispute,
            action=DisputeAuditLog.Action.EVIDENCE_UPLOADED,
            actor=user,
            description=f"{validated_value["file_type"]} uploaded by {user.role}.",
            diff={"file_url":[None, validated_value["file_url"]]},
        )

        publish_event(EventType.DISPUTE_STATEMENT_ADDED, {
           **_dispute_payload(dispute),
            "evidence_id": str(evidence.id),
            "file_type":   evidence.file_type,
            "uploaded_by": str(user.id), 
        })

        return Response({
            "success":True,
            "message":"Successfully uploaded evidence",
            "data":{
                "id":          str(evidence.id),
                "file_url":    evidence.file_url,
                "file_type":   evidence.file_type,
                "description": evidence.description,
                "created_at":  evidence.created_at.isoformat(),
            }
        },
            status=status.HTTP_201_CREATED,
        )

class MarkUnderReviewView(APIView):
    """
    POST /api/v1/disputes/{id}/review
    Admin picks up an OPEN dispute.
    
    Emits: disputes.dispute.under_review
    """

    permission_classes=[IsAuthenticated, IsAdmin]

    def post(self, request, pk):
        dispute, err = _get_dispute_or_404(pk)

        if err:
            return err

        serializer = MarkUnderReviewSerializer(
            data=request.data,
            context={"dispute": dispute},
        )
        serializer.is_valid(raise_exception=True)
        admin_notes = serializer.validated_data.get("admin_notes", "")

        old_status = dispute.status
        dispute.status = Dispute.Status.UNDER_REVIEW
        if admin_notes:
            dispute.admin_notes = admin_notes
        dispute.save(update_fields=["status", "admin_notes", "updated_at"])

        write_audit(
            dispute=dispute,
            action=DisputeAuditLog.Action.MARKED_UNDER_REVIEW,
            actor=request.user,
            description="Admin marked dispute as under review.",
            diff={"status": [old_status, Dispute.Status.UNDER_REVIEW]},
        )

        publish_event(EventType.DISPUTE_UNDER_REVIEW, {
             **_dispute_payload(dispute),
            "admin_id": str(request.user.id),
        })

        return Response({
            "success":True,
            "message":"Marked dispute as under review",
            "data":DisputeSerializer(dispute).data,

        },
status=status.HTTP_200_OK
        )
    
class ResolveView(APIView):
    """
    POST /api/v1/disputes/{id}/resolve
    Admin resolves with financial outcome.

    Emit: disputes.dispute.resolved
    Triggers: payments.refund_escrow OR payments.release_erscrow
    Transition: appointment to CONFIRMED or AUTO_RELEASED
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, pk):
        dispute, err = _get_dispute_or_404(pk)

        if err:
            return err

        serializer = ResolveSerializer(data=request.data, context={"dispute": dispute})

        serializer.is_valid(raise_exception=True)
        validated_value = serializer.validated_data

        # Update admin notes before resolution 
        if validated_value.get("admin_notes"):
            dispute.admin_notes = validated_value["admin_notes"]
            dispute.save(update_fields=["admin_notes"])

        try:
            resolved = resolve_dispute(
                dispute = dispute,
                resolution= validated_value["resolution"],
                resolution_notes= validated_value["resolution_notes"],
                admin_user= request.user,
                split_percent_seeker= validated_value.get("split_percent_seeker"),
            )
        except ValueError as exc:
            return error_response(data=str(exc), status_code=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "success": True,
                "message":"Dispute resolved successfully",
                "data": DisputeSerializer(resolved).data,
            },
            status=status.HTTP_200_OK
        )

class CloseView(APIView):
    """
    POST /api/v1/disputes/{id}/close

    Close a disptue without triggering a financial operation.
    Used for invalid, withdrawn disputes.
    escrow remains in its current state - admin must manually handle escrow via the payment admin panel if funds are affected.
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, pk):
        dispute, err = _get_dispute_or_404(pk)

        if err:
            return err

        serializer = CloserSerializer(data=request.data,
                                      context={"dispute":dispute })
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["reason"]

        old_status = dispute.status
        dispute.status = Dispute.Status.CLOSED
        dispute.admin_notes = reason
        dispute.resolved_by = request.user
        dispute.resolved_at = timezone.now()
        dispute.save(update_fields=[
            "status", "admin_notes",
            "resolved_by", "resolved_at", "updated_at",
        ])

        write_audit(
            dispute,
            action=DisputeAuditLog.Action.CLOSED,
            actor=request.user,
            description=f"Dispute closed: {reason}",
            diff={"status": [old_status, Dispute.Status.CLOSED]},
        )

        return Response({
            "success": True,
            "message": "Dispute closed successfully.",
            "data": DisputeSerializer(dispute).data,
        }, status=status.HTTP_200_OK)