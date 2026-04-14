import hashlib
import hmac
import json
import re
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.utils import timezone

from AI.api_caller import match_tasks_to_commits, verify_task_completion, verify_unmatched_completion
from projects.models import Project, Task
from .models import CommitEvent, UnrelatedCommit


# ── Signature verification ─────────────────────────────────────────────────────

def verify_github_signature(request) -> bool:
    secret = settings.GITHUB_WEBHOOK_SECRET
    if not secret:
        return False
    sig_header = request.headers.get('X-Hub-Signature-256', '')
    if not sig_header.startswith('sha256='):
        return False
    expected = hmac.new(
        secret.encode(), request.body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f'sha256={expected}', sig_header)


# ── Branch → slug matching ─────────────────────────────────────────────────────

def extract_slug_from_branch(branch: str) -> str | None:
    match = re.match(r'^(?:task|feature|feat|fix|chore)/(.+)$', branch)
    if match:
        return match.group(1)
    return branch if '/' not in branch else None


def get_repo_full_name(project: Project) -> str | None:
    """
    Normalizes stored repo values to owner/repo for GitHub API usage.
    Supports both full GitHub URLs and already-normalized owner/repo strings.
    """
    raw = (project.github_link or '').strip()
    if not raw:
        return None

    if raw.startswith('http://') or raw.startswith('https://'):
        parsed = urlparse(raw)
        path = (parsed.path or '').strip('/')
    else:
        path = raw.strip('/')

    if path.endswith('.git'):
        path = path[:-4]

    parts = path.split('/')
    if len(parts) >= 2 and parts[0] and parts[1]:
        return f"{parts[0]}/{parts[1]}"

    return None


# ── GitHub API helpers ─────────────────────────────────────────────────────────

def _github_headers(token: str) -> dict:
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }


def fetch_commit_detail(repo: str, sha: str, token: str) -> dict:
    """
    Fetches a single commit's file list + line counts from GitHub.
    Returns {"files": [...], "lines_added": N, "lines_deleted": N}
    """
    url = f'https://api.github.com/repos/{repo}/commits/{sha}'
    try:
        resp = requests.get(url, headers=_github_headers(token), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        files = [
            {
                'filename':  f.get('filename', ''),
                'additions': f.get('additions', 0),
                'deletions': f.get('deletions', 0),
            }
            for f in data.get('files', [])
        ]
        stats = data.get('stats', {})
        return {
            'files':         files,
            'lines_added':   stats.get('additions', 0),
            'lines_deleted': stats.get('deletions', 0),
        }
    except requests.RequestException:
        return {'files': [], 'lines_added': 0, 'lines_deleted': 0}


def fetch_diff_for_task(task: Task, token: str) -> str | None:
    """
    Fetches a unified diff across all CommitEvents linked to this task.
    Truncated to 6000 chars to stay within Gemini context limits.
    """
    repo = get_repo_full_name(task.project)
    if not repo:
        return None

    commits = task.commits.order_by('timestamp')
    if not commits.exists():
        return None

    oldest = commits.first().sha
    newest = commits.last().sha

    # Single commit — use commit endpoint directly
    if oldest == newest:
        url = f'https://api.github.com/repos/{repo}/commits/{newest}'
        accept = 'application/vnd.github.diff'
    else:
        url = f'https://api.github.com/repos/{repo}/compare/{oldest}...{newest}'
        accept = 'application/vnd.github.diff'

    headers = {**_github_headers(token), 'Accept': accept}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        diff = resp.text[:6000]
        if len(resp.text) > 6000:
            diff += '\n... [diff truncated]'
        return diff
    except requests.RequestException:
        return None


# ── Task matching ──────────────────────────────────────────────────────────────

def match_commit_to_task(project: Project, branch: str,
                         commits: list) -> Task | None:
    """
    Tier 1: exact slug match.
    Tier 2: AI fuzzy match on miss.
    Returns None if nothing matches with sufficient confidence.
    """
    # Tier 1
    slug = extract_slug_from_branch(branch)
    if slug:
        task = project.tasks.filter(
            slug=slug, status__in=['to-do', 'doing', 'done']
        ).first()
        if task:
            return task

    # Tier 2
    return match_tasks_to_commits(project, branch, commits)


# ── Completion policy application ──────────────────────────────────────────────

def apply_revert_policy(task: Task, verdict: dict):
    """
    Reverts a falsely-marked-done task according to project settings.
    Called when verification fails.
    """
    from projects.models import ProjectSettings

    try:
        policy = task.project.settings.completion_policy
    except ProjectSettings.DoesNotExist:
        policy = ProjectSettings.CompletionPolicy.HARD_BLOCK

    # Always revert
    task._change_reason = f"AI rejected completion: {verdict['reason']}"
    task.status = 'doing'
    task.save(update_fields=['status', 'updated_on'])

    if policy == ProjectSettings.CompletionPolicy.SOFT_WARN:
        _notify_developer_revert(task, verdict)

    elif policy == ProjectSettings.CompletionPolicy.SHAME_BLOCK:
        _notify_developer_revert(task, verdict)
        _send_shame_webhook(task.project, {
            'task_id':            task.id,
            'task_title':         task.title,
            'owner':              task.owner.user.username if task.owner else 'unknown',
            'hours_stalled':      0,
            'downstream_blocked': task.blocked_tasks.exclude(
                status__in=['done', 'archived']
            ).count(),
        }, (
            f"{task.owner.user.username if task.owner else 'Someone'} tried to "
            f"sneak '{task.title}' past the AI. "
            f"Gemini disagrees ({verdict['confidence']}% confidence incomplete). "
            f"{verdict['reason']}"
        ))


def apply_suggestion_policy(task: Task, verdict: dict):
    """
    Applies the suggestion policy when an unmatched commit looks like
    it completes a task the developer forgot to mark done.
    """
    from projects.models import ProjectSettings

    try:
        policy = task.project.settings.suggestion_policy
    except ProjectSettings.DoesNotExist:
        policy = ProjectSettings.SuggestionPolicy.SUGGEST

    if policy == ProjectSettings.SuggestionPolicy.AUTO:
        task._change_reason = f"Auto-completed by AI: {verdict['reason']}"
        task.status = 'done'
        task.save(update_fields=['status', 'updated_on'])

    elif policy == ProjectSettings.SuggestionPolicy.REVIEW:
        task._change_reason = f"AI-suggested completion (pending review): {verdict['reason']}"
        task.status = 'done'
        task.ai_suggested = True   # see note below
        task.save(update_fields=['status', 'updated_on'])

    elif policy == ProjectSettings.SuggestionPolicy.SUGGEST:
        # No DB change — just fire the webhook notification so plugin can prompt
        _notify_suggest_completion(task, verdict)


# ── Notification helpers ───────────────────────────────────────────────────────

def _notify_developer_revert(task: Task, verdict: dict):
    """Posts a warning to the team webhook about the revert."""
    _send_shame_webhook(task.project, {}, (
        f"Task '{task.title}' was reverted to 'doing'. "
        f"Reason: {verdict['reason']} "
        f"Missing: {', '.join(verdict.get('missing', []))}"
    ))


def _notify_suggest_completion(task: Task, verdict: dict):
    """Notifies team webhook to prompt developer to mark the task done."""
    _send_shame_webhook(task.project, {}, (
        f"Heads up: it looks like '{task.title}' might be done "
        f"({verdict['confidence']}% confidence). "
        f"{verdict['reason']} "
        f"Developer: please mark it done in the plugin if correct."
    ))


def _send_shame_webhook(project: Project, stall_data: dict, message: str):
    webhook_url = getattr(project.team, 'shame_webhook_url', None)
    if not webhook_url:
        return
    try:
        requests.post(
            webhook_url,
            json={'text': f'*SCRUMB — {project.name}*\n{message}'},
            timeout=5
        )
    except requests.RequestException:
        pass


# ── Unrelated commit storage ───────────────────────────────────────────────────

def store_unrelated_commit(project: Project, commit: dict,
                           branch: str, token: str | None):
    """
    Stores a commit that couldn't be matched to any task.
    Fetches file details from GitHub if token is available.
    """
    sha = commit.get('id', '')[:40]
    author_name = commit.get('author', {}).get('name', 'unknown')

    # Look up Developer by GitHub username if possible
    from Users.models import Developer
    developer = Developer.objects.filter(
        user__username=author_name
    ).first()

    detail = {'files': [], 'lines_added': 0, 'lines_deleted': 0}
    repo = get_repo_full_name(project)
    if token and repo:
        detail = fetch_commit_detail(repo, sha, token)

    from datetime import datetime
    try:
        ts = datetime.fromisoformat(commit.get('timestamp', ''))
    except (ValueError, TypeError):
        ts = timezone.now()

    UnrelatedCommit.objects.get_or_create(
        project=project,
        sha=sha,
        defaults={
            'developer':    developer,
            'branch':       branch,
            'message':      commit.get('message', '')[:500],
            'author':       author_name,
            'timestamp':    ts,
            'files_changed': detail['files'],
            'lines_added':  detail['lines_added'],
            'lines_deleted': detail['lines_deleted'],
        }
    )


# ── Stall detection ────────────────────────────────────────────────────────────

def detect_stalls(project: Project) -> list[dict]:
    cutoff = timezone.now() - timezone.timedelta(hours=48)
    stalls = []

    for task in project.tasks.filter(status='doing').prefetch_related('commits'):
        latest = task.commits.order_by('-timestamp').first()
        last_activity = latest.timestamp if latest else task.updated_on

        if last_activity < cutoff:
            hours_stalled = round(
                (timezone.now() - last_activity).total_seconds() / 3600
            )
            stalls.append({
                'task_id':            task.id,
                'task_title':         task.title,
                'owner':              task.owner.user.username if task.owner else 'unassigned',
                'hours_stalled':      hours_stalled,
                'downstream_blocked': task.blocked_tasks.exclude(
                    status__in=['done', 'archived']
                ).count(),
                'last_activity':      last_activity.isoformat(),
            })

    stalls.sort(key=lambda x: x['downstream_blocked'], reverse=True)
    return stalls


# ── Distraction score ──────────────────────────────────────────────────────────

def update_distraction_scores(project: Project):
    """
    Recalculates distraction score per developer based on unrelated commits
    in the last 7 days. Stored on Developer as a project-scoped annotation —
    used by get_daily_velocity and shame reports.
    """
    from django.db.models import Count, Sum
    from django.utils import timezone

    cutoff = timezone.now() - timezone.timedelta(days=7)

    scores = (
        UnrelatedCommit.objects
        .filter(project=project, timestamp__gte=cutoff, developer__isnull=False)
        .values('developer_id')
        .annotate(
            commit_count=Count('id'),
            lines_off_task=Sum('lines_added'),
        )
    )

    # Store on a simple cache dict attached to the project for now.
    # When Gopi builds the knowledge graph this feeds directly into it.
    project._distraction_scores = {
        s['developer_id']: {
            'commits_off_task': s['commit_count'],
            'lines_off_task':   s['lines_off_task'] or 0,
        }
        for s in scores
    }
    return project._distraction_scores


# ── Main orchestrator ──────────────────────────────────────────────────────────

def process_push_event(payload: dict) -> dict:
    from .auth import get_installation_access_token

    installation_id = payload.get('installation', {}).get('id')
    if not installation_id:
        return {'error': 'no installation_id'}

    project = Project.objects.filter(
        github_installation_id=installation_id
    ).select_related('team', 'settings').prefetch_related('tasks').first()

    if not project:
        return {'error': f'no project for installation {installation_id}'}

    ref     = payload.get('ref', '')
    branch  = ref.replace('refs/heads/', '')
    commits = payload.get('commits', [])
    if not commits:
        return {'skipped': 'no commits'}

    # Get a fresh installation token for all GitHub API calls this event
    token = get_installation_access_token(installation_id)

    result = {
        'project':            project.name,
        'branch':             branch,
        'task_matched':       None,
        'unrelated_stored':   0,
        'verification':       None,
        'suggestion':         None,
        'stalls':             [],
        'distraction_scores': {},
    }

    # ── Match commits to a task ────────────────────────────────────────────────
    task = match_commit_to_task(project, branch, commits)

    if task:
        status_before = task.status
        result['task_matched'] = {
            'id': task.id,
            'title': task.title,
            'status_before': status_before,
        }

        # Always log matched commit activity first so downstream checks use fresh history.
        _handle_task_activity(task, commits, payload, result)

        skip_check = getattr(
            getattr(project, 'settings', None),
            'skip_ai_completion_check', False
        )

        if skip_check:
            result['verification'] = {'action': 'skipped_by_settings'}
        else:
            verdict = verify_task_completion(
                task,
                diff=(fetch_diff_for_task(task, token) if token else None)
            )
            result['verification'] = verdict

            if status_before == 'done':
                if not verdict['verified']:
                    apply_revert_policy(task, verdict)
                    result['verification']['action'] = 'reverted'
                else:
                    result['verification']['action'] = 'confirmed'
            elif verdict['verified']:
                task._change_reason = (
                    f"Auto-completed by AI after push verification: "
                    f"{verdict.get('reason', '')}"
                )
                task.status = 'done'
                task.save(update_fields=['status', 'updated_on'])
                result['verification']['action'] = 'auto_completed'
            else:
                result['verification']['action'] = 'kept_in_progress'

        task.refresh_from_db(fields=['status'])
        result['task_matched']['status_after'] = task.status

    else:
        # ── Path C: no match — check if it looks like a completed task ─────────
        for commit in commits:
            store_unrelated_commit(project, commit, branch, token)
        result['unrelated_stored'] = len(commits)

        unmatched_verdict = verify_unmatched_completion(
            project, branch, commits, token
        )
        result['suggestion'] = unmatched_verdict

        if unmatched_verdict['looks_complete'] and unmatched_verdict['task_id']:
            candidate_task = project.tasks.filter(
                id=unmatched_verdict['task_id'],
                status__in=['to-do', 'doing']
            ).first()
            if candidate_task:
                apply_suggestion_policy(candidate_task, unmatched_verdict)
                result['suggestion']['applied_to'] = candidate_task.title

    # ── Always run stall detection and update distraction scores ───────────────
    stalls = detect_stalls(project)
    result['stalls'] = stalls
    result['distraction_scores'] = update_distraction_scores(project)

    if stalls and stalls[0]['downstream_blocked'] > 0:
        from AI.api_caller import shame_team
        from projects.logic import get_stalled_tasks
        roast = shame_team(get_stalled_tasks(project), {'name': project.team.name})
        _send_shame_webhook(project, stalls[0], roast)

    return result


def _handle_task_activity(task: Task, commits: list, payload: dict, result: dict):
    author_name = payload.get('pusher', {}).get('name', 'unknown')
    moved = False

    if task.status == 'to-do':
        task._change_reason = f'Auto-started by push from {author_name}'
        task.status = 'doing'
        task.save(update_fields=['status', 'updated_on'])
        moved = True

    from datetime import datetime
    for commit in commits:
        sha = commit.get('id', '')[:40]
        try:
            ts = datetime.fromisoformat(commit.get('timestamp', ''))
        except (ValueError, TypeError):
            ts = timezone.now()

        CommitEvent.objects.get_or_create(
            task=task, sha=sha,
            defaults={
                'author':    commit.get('author', {}).get('name', author_name),
                'message':   commit.get('message', ''),
                'timestamp': ts,
            }
        )

    result['task_matched']['moved_to_doing'] = moved
    result['task_matched']['commits_logged'] = len(commits)