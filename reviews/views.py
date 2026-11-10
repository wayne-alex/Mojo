from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Rating
from .services import submit_rating


class RateJobView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            r = submit_rating(
                pk, request.user,
                score=request.data.get("score"),
                comment=request.data.get("comment", ""),
            )
        except DjangoValidationError as e:
            return Response({"error": e.messages}, status=400)
        except Exception as e:
            return Response({"error": [str(e)]}, status=400)
        return Response(
            {"id": str(r.id), "score": r.score, "direction": r.direction},
            status=status.HTTP_201_CREATED,
        )


class WorkerReviewsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, worker_id):
        qs = Rating.objects.filter(
            subject_id=worker_id,
            direction=Rating.Direction.CLIENT_TO_WORKER,
        ).order_by("-created_at").values(
            "id", "score", "comment", "created_at",
        )
        return Response({"count": qs.count(), "results": list(qs)})