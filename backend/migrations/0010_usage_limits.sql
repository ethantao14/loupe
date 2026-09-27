begin;

create table public.usage_counters (
    day date not null,
    scope text not null check (scope in ('visitor', 'ip', 'total')),
    key text not null,
    count integer not null default 0,
    primary key (day, scope, key)
);

alter table public.usage_counters enable row level security;
revoke all on public.usage_counters from anon, authenticated;

create function public.consume_message_quota(
    visitor uuid,
    ip_hash text,
    visitor_limit integer,
    ip_limit integer,
    total_limit integer
)
returns text
language plpgsql
set search_path = ''
as $$
declare
    today date := (now() at time zone 'utc')::date;
    total_count integer;
    ip_count integer;
    visitor_count integer;
begin
    -- Every call locks in this order, including when a limit is disabled.
    insert into public.usage_counters (day, scope, key)
    values (today, 'total', 'all') on conflict do nothing;
    select count into total_count from public.usage_counters
    where day = today and scope = 'total' and key = 'all' for update;

    insert into public.usage_counters (day, scope, key)
    values (today, 'ip', ip_hash) on conflict do nothing;
    select count into ip_count from public.usage_counters
    where day = today and scope = 'ip' and key = ip_hash for update;

    insert into public.usage_counters (day, scope, key)
    values (today, 'visitor', visitor::text) on conflict do nothing;
    select count into visitor_count from public.usage_counters
    where day = today and scope = 'visitor' and key = visitor::text for update;

    delete from public.usage_counters where day < today - 7;

    if total_limit is not null and total_count >= total_limit then
        return 'total';
    end if;
    if ip_limit is not null and ip_count >= ip_limit then
        return 'ip';
    end if;
    if visitor_limit is not null and visitor_count >= visitor_limit then
        return 'visitor';
    end if;

    update public.usage_counters set count = count + 1
    where day = today and (
        (scope = 'total' and key = 'all')
        or (scope = 'ip' and key = ip_hash)
        or (scope = 'visitor' and key = visitor::text)
    );
    return null;
end;
$$;

revoke execute on function public.consume_message_quota(uuid, text, integer, integer, integer) from public;
revoke execute on function public.consume_message_quota(uuid, text, integer, integer, integer) from anon, authenticated;
grant execute on function public.consume_message_quota(uuid, text, integer, integer, integer) to service_role;

commit;
