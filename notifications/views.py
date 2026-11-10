from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .services import mark_read, mark_all_read


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        unread_only = request.query_params.get("unread") == "1"
        qs = Notification.objects.filter(user=request.user)
        if unread_only:
            qs = qs.filter(read=False)
        data = list(qs.values(
            "id", "kind", "title", "body", "link", "reference",
            "read", "created_at",
        ))
        unread_count = Notification.objects.filter(
            user=request.user, read=False,
        ).count()
        return Response({"unread_count": unread_count, "results": data})


class MarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        mark_read(request.user, pk)
        return Response({"ok": True})


class MarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        n = mark_all_read(request.user)
        return Response({"updated": n})