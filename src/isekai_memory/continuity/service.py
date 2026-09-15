"""Continuity dispatcher, after common MCP/REST schema and authorization checks."""

from isekai_memory.continuity import (
    checkpoints,
    delivery,
    events,
    overview,
    policies,
    presence,
    presence_reads,
    reads,
    usage,
    usage_reads,
    work,
)

HANDLERS = {
    "memory_collaboration_events": events.listing,
    "memory_collaboration_events_prune": events.prune,
    "memory_usage_policy_get": usage.policy_get,
    "memory_usage_policy_set": usage.policy_set,
    "memory_usage_register": usage.register,
    "memory_usage_report": usage.report,
    "memory_usage_prune": usage.prune,
    "memory_usage_list": usage_reads.listing,
    "memory_usage_summary": usage_reads.summary,
    "memory_presence_policy_get": presence.policy_get,
    "memory_presence_policy_set": presence.policy_set,
    "memory_presence_register": presence.register,
    "memory_presence_heartbeat": presence.heartbeat,
    "memory_presence_end": presence.end,
    "memory_presence_prune": presence.prune,
    "memory_presence_list": presence_reads.listing,
    "memory_presence_users": presence_reads.users,
    "memory_collaboration_overview": overview.overview,
    "memory_collaboration_list": overview.listing,
    "memory_continuity_policy_set": policies.set_policy,
    "memory_continuity_policy_get": policies.get_policy,
    "memory_continuity_members": reads.members,
    "memory_checkpoint_save": checkpoints.save,
    "memory_checkpoint_read": checkpoints.read,
    "memory_checkpoint_forget": checkpoints.forget,
    "memory_continuity_publish": delivery.publish,
    "memory_continuity_status": reads.status,
    "memory_continuity_read": delivery.read,
    "memory_continuity_ack": delivery.ack,
    "memory_continuity_reassign": delivery.reassign,
    "memory_continuity_claim": work.claim,
    "memory_continuity_renew": work.renew,
    "memory_continuity_release": work.release,
}
VIEWS = {"memory_continuity_inbox": "inbox", "memory_checkpoint_list": "checkpoints", "memory_continuity_history": "history"}


async def dispatch(name, arguments, *, principal):
    if name in VIEWS:
        return await reads.listing(arguments, principal=principal, view=VIEWS[name])
    return await HANDLERS[name](arguments, principal=principal)
