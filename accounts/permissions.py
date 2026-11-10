from rest_framework.permissions import BasePermission


class IsClient(BasePermission):
    message = "Only clients can perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated
                    and getattr(request.user, "role", None) == "client")


class IsWorker(BasePermission):
    message = "Only workers can perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated
                    and getattr(request.user, "role", None) == "worker")


class IsAdminRole(BasePermission):
    message = "Admins only."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated
                    and getattr(request.user, "role", None) == "admin")