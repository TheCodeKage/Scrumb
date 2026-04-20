import requests

from github.auth import get_token, get_installation_token
from projects.models import Project
from django.core.cache import cache


def get_github_installation(project: Project) -> bool | None:
    """
    Checks whether the given project's GitHub repository has access enabled under a GitHub application
    installation and retrieves the installation ID for further use.

    Parameters:
    project (Project): The object representing the project for which GitHub repository access
    needs to be checked. It is expected to have an attribute 'github_repo_slug'
    representing the repository slug in GitHub.

    Returns:
    bool | None: Returns True if access is enabled, False if the repository is not found (404).
    Returns None in case of an unexpected error or status from the GitHub API.
    """

    url = f"https://api.github.com/repos/{project.github_repo_slug}/installation"
    response = requests.get(url,
                            headers={"Authorization": f"Bearer {get_token()}", "Accept": "application/vnd.github+json"})

    if response.status_code == 200:
        project.github_installation_id = response.json()["id"]
        project.save()
        return True
    elif response.status_code == 404:
        return False
    else:
        response.raise_for_status()
        return None


def delete_installation(installation_id: int):
    """
    Deletes a GitHub installation and removes its association with projects.

    This function updates all projects associated with the given GitHub installation
    ID by setting their `github_installation_id` to `None`. It is useful for cleanup
    operations when a GitHub installation is no longer available or is revoked.

    Args:
        installation_id (int): The unique identifier of the GitHub installation
            to be deleted.

    Returns:
        None
    """
    Project.objects.filter(github_installation_id=installation_id).update(github_installation_id=None)


def get_installation_repos(installation_id):
    """
    Returns a list of all GitHub repositories associated with the given installation ID.
    """
    token = get_installation_token(installation_id)

    url = "https://api.github.com/installation/repositories"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }

    full_names = []
    page = 1

    while True:
        response = requests.get(
            url,
            headers=headers,
            params={"per_page": 100, "page": page}
        )
        response.raise_for_status()

        data = response.json()["repositories"]

        # 👇 only extract what you need
        full_names.extend(repo["full_name"] for repo in data)

        if len(data) < 100:
            break

        page += 1

    return full_names


def _update_projects(installation_id):
    repos = set(get_installation_repos(installation_id))

    # link matching repos
    Project.objects.filter(
        github_repo_slug__in=repos
    ).update(github_installation_id=installation_id)

    # unlink removed repos
    Project.objects.filter(
        github_installation_id=installation_id
    ).exclude(
        github_repo_slug__in=repos
    ).update(github_installation_id=None)


def safe_sync(installation_id):
    key = f"sync_lock_{installation_id}"

    if cache.get(key):
        return

    cache.set(key, True, timeout=60)  # 1 min lock
    _update_projects(installation_id)


def match_push_to_project(data):
    pass

"""
Problems in current execution

Any user can set github repo slug without authentication, and above methods check repo slug 
and match with installation id without authentication. This allows anyone to access Scrumb
provided features on other users' private repositories by simply guessing the repo slug.

github provides webhooks that are triggered when a repo is added/removed from an installation.
Using that is cheaper and faster in execution.
"""