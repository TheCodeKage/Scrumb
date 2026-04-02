from functools import wraps

from django.db import transaction

from .models import Invitation, Membership, Developer, Team


# ----------------------------- Helper Functions ----------------------------------------------------
def validate_team_invite(inviter: Developer, invited: Developer, team: Team):
    if not team.is_leader(inviter):
        return False, "Only team leaders can send invitations."
    if team.is_member(invited):
        return False, "User is already a member of the team."
    if Invitation.objects.filter(team=team, developer=invited, status=Invitation.Status.PENDING).exists():
        return False, "User has already been invited to the team."
    return True, None


def validate_join_request(developer: Developer, team: Team):
    if team.is_member(developer):
        return False, "User is already a member of the team."
    if Invitation.objects.filter(team=team, developer=developer, status=Invitation.Status.PENDING).exists():
        return False, "User has already requested to join the team."
    return True, None


def create_invitation(invited: Developer, team: Team, initiator: Invitation.Initiator):
    Invitation.objects.create(
        team=team,
        developer=invited,
        initiated_by=initiator,
        status=Invitation.Status.PENDING
    )


def create_membership(developer: Developer, team: Team, role: Membership.Role = Membership.Role.MEMBER):
    Membership.objects.create(
        team=team,
        developer=developer,
        role=role
    )


def validate_invite_acceptance(invitation: Invitation):
    if invitation.status != Invitation.Status.PENDING:
        return False, "Invitation is not pending."
    if invitation.team.is_member(invitation.developer):
        return False, "User is already a member of the team."
    if invitation.initiated_by == Invitation.Initiator.DEVELOPER:
        return False, "Join requests must be accepted/declined by team leaders, not the developer."
    return True, None


def validate_join_request_acceptance(invitation: Invitation):
    if invitation.status != Invitation.Status.PENDING:
        return False, "Join request is not pending."
    if invitation.team.is_member(invitation.developer):
        return False, "User is already a member of the team."
    if invitation.initiated_by == Invitation.Initiator.TEAM:
        return False, "Invitations must be accepted/rejected by developers, not team leaders."
    return True, None


def validate_action(validator):
    """
    Decorator to run a validator before executing an action.
    If validation fails, returns a standardized result.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            valid, error = validator(*args, **kwargs)
            if not valid:
                return False, error
            return func(*args, **kwargs)

        return wrapper

    return decorator


# -----------------------------------------------------------------------------------------------------

# ----------------------------------------- Action Functions ------------------------------------------
@validate_action(validate_team_invite)
def send_invitation(inviter: Developer, invited: Developer, team: Team):
    create_invitation(invited, team, Invitation.Initiator.TEAM)
    return True, None



@validate_action(validate_join_request)
def send_join_request(developer: Developer, team: Team):
    create_invitation(developer, team, Invitation.Initiator.DEVELOPER)
    return True, None



@validate_action(validate_invite_acceptance)
def accept_invitation(invitation: Invitation):
    with transaction.atomic():
        invitation.status = Invitation.Status.ACCEPTED
        invitation.save()
        create_membership(invitation.developer, invitation.team)
    return True, None



@validate_action(validate_invite_acceptance)
def decline_invitation(invitation: Invitation):
    invitation.status = Invitation.Status.DECLINED
    invitation.save()
    return True, None



@validate_action(validate_join_request_acceptance)
def accept_join_request(invitation: Invitation):
    with transaction.atomic():
        invitation.status = Invitation.Status.ACCEPTED
        invitation.save()
        create_membership(invitation.developer, invitation.team, Membership.Role.MEMBER)
    return True, None



@validate_action(validate_join_request_acceptance)
def decline_join_request(invitation: Invitation):
    invitation.status = Invitation.Status.DECLINED
    invitation.save()
# -----------------------------------------------------------------------------------------------------
