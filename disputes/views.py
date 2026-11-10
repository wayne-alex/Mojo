from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from .models import Dispute, Evidence
from .services import open_dispute, submit_evidence, resolve


class OpenDisputeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            d = open_dispute(
                pk, request.user,
                reason=request.data.get("reason", ""),
                evidence_text=request.data.get("evidence_text", ""),
                evidence_file_url=request.data.get("evidence_file_url", ""),
            )
        except DjangoValidationError as e:
            return Response({"error": e.messages}, status=400)
        return Response({"id": str(d.id), "status": d.status}, status=201)


class SubmitEvidenceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            ev = submit_evidence(
                pk, request.user,
                text=request.data.get("text", ""),
                file_url=request.data.get("file_url", ""),
            )
        except DjangoValidationError as e:
            return Response({"error": e.messages}, status=400)
        return Response({"id": str(ev.id)}, status=201)


class ResolveDisputeView(APIView):
    permission_classes = [IsAdminRole]

    def post(self, request, pk):
        try:
            d = resolve(
                pk, request.user,
                outcome=request.data.get("outcome"),
                note=request.data.get("note", ""),
                client_share=request.data.get("client_share"),
                worker_share=request.data.get("worker_share"),
            )
        except DjangoValidationError as e:
            return Response({"error": e.messages}, status=400)
        return Response({
            "id": str(d.id), "status": d.status,
            "client_refund": str(d.client_refund),
            "worker_payout": str(d.worker_payout),
        })


class DisputeDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            d = Dispute.objects.get(pk=pk)
        except Dispute.DoesNotExist:
            return Response({"error": ["Not found"]}, status=404)
        # Only parties or admins can view
        if (request.user.role != "admin"
                and request.user.id not in (d.job.client_id, d.job.accepted_bid.worker_id)):
            return Response({"error": ["Forbidden"]}, status=403)
        return Response({
            "id": str(d.id),
            "job_id": str(d.job_id),
            "reason": d.reason,
            "status": d.status,
            "resolution_note": d.resolution_note,
            "client_refund": str(d.client_refund) if d.client_refund is not None else None,
            "worker_payout": str(d.worker_payout) if d.worker_payout is not None else None,
            "evidence": list(d.evidence.values("id", "submitted_by", "text", "file_url", "created_at")),
            "created_at": d.created_at,
        })