from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from .services import find_accounts_sharing_ip, find_accounts_sharing_device
from .models import FraudFlag


class SharedIpView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        ip = request.query_params.get("ip")
        qs = find_accounts_sharing_ip(ip)
        return Response({
            "ip": ip,
            "accounts": [
                {"id": str(u.id), "username": u.username, "phone": u.phone, "role": u.role}
                for u in qs
            ],
        })


class SharedDeviceView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        ua = request.query_params.get("ua_hash")
        qs = find_accounts_sharing_device(ua)
        return Response({
            "ua_hash": ua,
            "accounts": [{"id": str(u.id), "username": u.username, "role": u.role} for u in qs],
        })


class FraudFlagListView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        qs = FraudFlag.objects.all().values(
            "id", "user_id", "reason", "note", "created_at",
        )
        return Response({"count": qs.count(), "results": list(qs)})