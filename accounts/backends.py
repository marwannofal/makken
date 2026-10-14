from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
from django.views.decorators.debug import sensitive_variables


class EmailOrUsernameBackend(ModelBackend):
    """Use the existing user model and Django's password verification."""

    @sensitive_variables()
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = username if username is not None else kwargs.get(User.USERNAME_FIELD)
        if not isinstance(identifier, str) or not isinstance(password, str):
            return None
        identifier = identifier.strip()
        if not identifier or not password or len(identifier) > 254 or len(password) > 1024:
            return None

        query = Q(**{User.USERNAME_FIELD: identifier})
        if identifier and "@" in identifier:
            query |= Q(**{f"{User.get_email_field_name()}__iexact": identifier})
        candidates = list(User._default_manager.filter(query).distinct()[:2])
        if len(candidates) != 1:
            # Match Django's missing-user password-hash work; reject ambiguous emails.
            User().set_password(password)
            return None

        user = candidates[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
