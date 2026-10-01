"""Disposable database only: automated discovery after a receiver disappears."""
import secrets

from tests.test_experience_postgres import harness  # noqa: F401


async def test_expired_claim_is_automatically_discovered_and_reclaimable(harness):  # noqa: F811 - shared pytest fixture
    h = harness
    saved = await h.source()
    identity = saved['handoff_id']
    first = await h.call('memory_handoff_claim', {
        'handoff_id': identity, 'claim_token': secrets.token_urlsafe(32)})
    # Advance this isolated record's lease; the original receiver never reconnects.
    await h.pool.execute("UPDATE handoffs SET claim_lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", identity)
    automatic = await h.call('memory_handoff_list', {'exclude_own': True}, role='admin2')
    visible = await h.call('memory_handoff_inbox', {'view': 'available'}, role='admin2')
    assert identity in [v['id'] for v in automatic]
    assert identity in [v['handoff_id'] for v in visible['items']]
    second = await h.call('memory_handoff_claim', {
        'handoff_id': identity, 'claim_token': secrets.token_urlsafe(32)}, role='admin2')
    assert second['claim_generation'] == first['claim_generation'] + 1
    print('EXPIRED_DISCOVERY', {'automatic_count': len(automatic), 'manual_available': len(visible['items']),
                               'new_generation': second['claim_generation']})


async def test_received_history_remains_actor_scoped_after_ack(harness):  # noqa: F811 - shared pytest fixture
    h = harness
    saved = await h.source()
    args = {'handoff_id': saved['handoff_id'], 'claim_token': secrets.token_urlsafe(32)}
    claimed = await h.call('memory_handoff_claim', args)
    await h.call('memory_handoff_ack', {**args, 'claim_generation': claimed['claim_generation']})
    history = await h.call('memory_handoff_inbox', {'view': 'received'})
    assert [row['handoff_id'] for row in history['items']] == [saved['handoff_id']]
    assert history['items'][0]['delivery_state'] == 'acknowledged'
    other = await h.call('memory_handoff_inbox', {'view': 'received'}, role='admin2')
    assert not other['items']
    available = await h.call('memory_handoff_list', {}, role='admin2')
    assert saved['handoff_id'] not in [row['id'] for row in available]
