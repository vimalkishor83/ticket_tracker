from datetime import datetime, timedelta, timezone

# DB stores everything in UTC. We show everything in AWST (Perth time) on
# screen, no matter where the user is logging in from. Perth doesn't use DST
# so offset is always +8.
AWST_OFFSET_HOURS = 8


def utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_awst(dt):
    if dt is None:
        return None
    return dt + timedelta(hours=AWST_OFFSET_HOURS)
