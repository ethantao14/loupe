begin;

create table if not exists public.memories (
    id uuid primary key default gen_random_uuid(),
    seq bigserial not null,
    fact text not null,
    created_at timestamptz not null default now()
);

create index if not exists memories_seq_idx on public.memories (seq);

-- Tables in public are reachable through the Data API, so do not rely on the
-- project setting that enables row level security. With it on and no policies
-- defined, only the service role the backend uses can reach the rows.
alter table public.memories enable row level security;
alter table public.messages enable row level security;
alter table public.steps enable row level security;

revoke all on public.memories from anon, authenticated;
revoke all on public.messages from anon, authenticated;
revoke all on public.steps from anon, authenticated;

alter table public.steps drop constraint if exists steps_kind_check;
alter table public.steps add constraint steps_kind_check
    check (kind in ('thinking', 'tool_call', 'tool_result', 'answer', 'memory'));

create or replace function public.insert_memory(fact text)
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
    memory public.memories%rowtype;
begin
    insert into public.memories (fact)
    values (insert_memory.fact)
    returning * into memory;

    return to_jsonb(memory);
end;
$$;

revoke execute on function public.insert_memory(text) from public;
revoke execute on function public.insert_memory(text) from anon, authenticated;
grant execute on function public.insert_memory(text) to service_role;

commit;
