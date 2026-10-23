from services.time_utils import to_awst

DISPLAY_FORMAT = '%d-%b-%Y'
INPUT_FORMAT = '%Y-%m-%d'


def fmt_date_display(d, empty='–'):
    return d.strftime(DISPLAY_FORMAT) if d else empty


def fmt_date_input(d):
    return d.strftime(INPUT_FORMAT) if d else ''


def fmt_datetime_display(dt, empty='–'):
    # dt comes from DB in UTC, convert to AWST before showing
    if not dt:
        return empty
    return to_awst(dt).strftime(f'{DISPLAY_FORMAT} %H:%M')


def fmt_date_only_awst(dt, empty='–'):
    # for columns like created_at where we only want the date part, in AWST
    if not dt:
        return empty
    return to_awst(dt).strftime(DISPLAY_FORMAT)
