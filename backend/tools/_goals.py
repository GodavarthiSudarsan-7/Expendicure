"""Shared helper: load the authenticated user's savings goals for a tool call.

Read-only. Identity is ``ctx.user_id`` (from the token) — never an argument.
Any failure to reach the goal store returns ``[]`` so goal-unaware behaviour
still works.
"""


def goals_for(ctx, *, status="active"):
    repo = ctx.repo_factory()
    getter = getattr(repo, "get_savings_goals", None)
    if getter is None:
        return []
    try:
        return list(getter(ctx.user_id, status=status) or [])
    except TypeError:
        # a repo whose get_savings_goals doesn't take status=
        try:
            return list(getter(ctx.user_id) or [])
        except Exception:
            return []
    except Exception:
        return []


def goal_for(ctx, goal_id):
    repo = ctx.repo_factory()
    getter = getattr(repo, "get_savings_goal", None)
    if getter is None:
        return None
    try:
        return getter(ctx.user_id, int(goal_id))
    except Exception:
        return None
