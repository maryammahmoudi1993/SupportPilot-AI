"""Accounts views."""

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "is_active"]


class UserViewSet(viewsets.ModelViewSet):
    """User viewset."""

    queryset = User.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    @action(detail=False, methods=["get"])
    def me(self, request):
        """Get current user."""
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)
